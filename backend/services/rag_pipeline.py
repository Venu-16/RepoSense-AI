import os
import re
from typing import Any, Optional

from langchain.chains import RetrievalQA
from langchain.chat_models import ChatOpenAI
from langchain.docstore.document import Document
from langchain.llms.base import LLM
from langchain.prompts import PromptTemplate
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import FAISS

from backend.services.embeddings import EmbeddingProvider


class RAGPipeline:
    _singleton: Optional["RAGPipeline"] = None

    def __init__(self) -> None:
        self.embedding_provider = EmbeddingProvider()
        self.llm = self._build_llm()
        self.stores: dict[str, FAISS] = {}
        self.chat_history: dict[str, list[dict[str, str]]] = {}

    @classmethod
    def get_instance(cls) -> "RAGPipeline":
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def _build_llm(self):
        # Prefer OpenAI when an API key is available.
        if os.getenv("OPENAI_API_KEY"):
            model_name = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
            return ChatOpenAI(model_name=model_name, temperature=0.1)

        # Use HuggingFaceHub inference if the HF API token is configured.
        hf_token = os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
        if hf_token:
            os.environ.setdefault("HUGGINGFACEHUB_API_TOKEN", hf_token)
            try:
                from langchain.llms import HuggingFaceHub

                model_name = os.getenv("HF_LLM_MODEL", "google/flan-t5-small")
                return HuggingFaceHub(
                    repo_id=model_name,
                    model_kwargs={"temperature": 0.1, "max_new_tokens": 128},
                )
            except Exception as exc:
                import logging

                logging.warning(
                    f"Failed to initialize HuggingFaceHub LLM: {exc}. Falling back to local model."
                )

        # Fall back to a local Hugging Face transformer if available.
        try:
            from transformers import pipeline

            model_name = os.getenv("HF_LLM_MODEL", "distilgpt2")
            task_name = os.getenv("HF_LLM_TASK", "text-generation")
            pipe = pipeline(
                task_name,
                model=model_name,
                tokenizer=model_name,
                device=-1,
                trust_remote_code=False,
            )
            return self._create_transformers_llm(pipe)
        except ImportError:
            return self._create_mock_llm()
        except Exception as exc:
            import logging

            logging.warning(
                f"Failed to initialize local Hugging Face model: {exc}. Using mock LLM."
            )
            return self._create_mock_llm()

    def _create_transformers_llm(self, pipe):
        from langchain.callbacks.manager import CallbackManagerForLLMRun

        class TransformersPipelineLLM(LLM):
            @property
            def _llm_type(self) -> str:
                return "transformers"

            def _call(
                self,
                prompt: str,
                stop: Optional[list[str]] = None,
                run_manager: Optional[CallbackManagerForLLMRun] = None,
                **kwargs: Any,
            ) -> str:
                params = {**kwargs}
                params["temperature"] = float(params.get("temperature", 0.1))
                params["max_new_tokens"] = min(int(params.get("max_new_tokens", 128)), 128)
                if "top_p" not in params:
                    params["top_p"] = 0.95
                if "repetition_penalty" not in params:
                    params["repetition_penalty"] = 1.2
                if "do_sample" not in params:
                    params["do_sample"] = params["temperature"] > 0
                if "pad_token_id" not in params:
                    params["pad_token_id"] = getattr(pipe.tokenizer, "eos_token_id", 0)

                max_input_length = getattr(pipe.tokenizer, "model_max_length", 1024) or 1024
                tokenized = pipe.tokenizer(
                    prompt,
                    return_tensors="pt",
                    truncation=True,
                    max_length=max_input_length,
                )
                truncated_prompt = pipe.tokenizer.decode(
                    tokenized["input_ids"][0],
                    skip_special_tokens=True,
                )

                output = pipe(truncated_prompt, **params)
                if isinstance(output, list):
                    first = output[0]
                    if isinstance(first, dict):
                        text = first.get("generated_text") or first.get("text") or str(first)
                    else:
                        text = str(first)
                elif isinstance(output, dict):
                    text = output.get("generated_text") or output.get("text") or str(output)
                else:
                    text = str(output)

                # Strip the echoed prompt from the model output when using the local transformer pipeline.
                for prefix in (prompt, truncated_prompt):
                    if text.startswith(prefix):
                        text = text[len(prefix) :]
                        break
                text = text.lstrip("\n ")

                if stop is not None:
                    from langchain.llms.utils import enforce_stop_tokens

                    text = enforce_stop_tokens(text, stop)
                return text

        return TransformersPipelineLLM()

    def _create_mock_llm(self):
        """Create an enhanced mock LLM that extracts info from context."""
        from langchain.llms.base import LLM
        from langchain.callbacks.manager import CallbackManagerForLLMRun
        from typing import Optional, List, Any
        import re

        class EnhancedMockLLM(LLM):
            @property
            def _llm_type(self) -> str:
                return "enhanced-mock"

            def _call(
                self,
                prompt: str,
                stop: Optional[List[str]] = None,
                run_manager: Optional[CallbackManagerForLLMRun] = None,
                **kwargs: Any,
            ) -> str:
                """Extract and summarize information from the context."""
                try:
                    # Extract the context section from the prompt. The default
                    # RetrievalQA prompt and the mock-friendly prompt both use
                    # these labels, but vary slightly in formatting.
                    context_match = re.search(
                        r"(?:Context:|Use the following pieces of context to answer the question at the end\.)(.*?)(?:\n\s*Question:|\n\s*Helpful Answer:|$)",
                        prompt,
                        re.DOTALL,
                    )
                    question_match = re.search(
                        r"(?:Question:|Question\s*:)(.*?)(?:\n\s*Helpful Answer:|\n\s*Answer:|$)",
                        prompt,
                        re.DOTALL,
                    )

                    context = context_match.group(1).strip() if context_match else ""
                    question = question_match.group(1).strip() if question_match else ""
                    
                    if not context:
                        return "I don't have any context available to answer this question. Please ensure the repository has been properly ingested."
                    
                    # Extract key information from context
                    lines = [line.strip() for line in context.split('\n') if line.strip()]
                    
                    # Try to find relevant lines that match the question
                    response_lines = []
                    
                    # Keywords from question to match in context
                    question_words = set(word.lower() for word in re.findall(r'\b\w+\b', question))
                    
                    for line in lines:
                        line_lower = line.lower()
                        # If line contains question keywords or seems relevant
                        if any(word in line_lower for word in question_words if len(word) > 3):
                            response_lines.append(line)
                        # Also include lines that look like definitions or descriptions
                        elif any(keyword in line_lower for keyword in ['is', 'are', 'does', 'can', 'provide', 'use', 'help', 'create']):
                            response_lines.append(line)
                    
                    if response_lines:
                        # Take first few relevant lines
                        summary = ' '.join(response_lines[:5])
                        # Limit length
                        if len(summary) > 500:
                            summary = summary[:497] + "..."
                        return summary
                    else:
                        # If no specific matches, provide general info from context
                        return ' '.join(lines[:3]) if lines else "Unable to generate a response based on the available context."
                        
                except Exception as e:
                    return f"Based on the provided context, I can see relevant information in the source files. Please refer to the retrieved documents for specific details."

        return EnhancedMockLLM()

    def _summarize_documents_fallback(self, query: str, documents: list[Document]) -> str:
        if not documents:
            return "I couldn't retrieve relevant repository content. Please try a different question."

        query_terms = set(re.findall(r"\b\w+\b", query.lower()))
        summary_lines: list[str] = []

        for document in documents:
            for line in document.page_content.splitlines():
                line_text = line.strip()
                if not line_text:
                    continue
                normalized = line_text.lower()
                if any(term in normalized for term in query_terms if len(term) > 3):
                    summary_lines.append(line_text)
                    break

        if not summary_lines:
            for document in documents[:3]:
                summary_lines.extend(
                    [line.strip() for line in document.page_content.splitlines() if line.strip()][:2]
                )

        if not summary_lines:
            return "I found relevant files, but could not extract a concise answer. Please ask a simpler question."

        summary = " ".join(summary_lines)
        return summary[:1000] + ("..." if len(summary) > 1000 else "")

    def _split_code(self, document: Document) -> list[Document]:
        text = document.page_content
        split_pattern = r"(?=^(?:def |class |function |const |let |var |export |async |public |private |protected ))"
        chunks: list[Document] = []
        for chunk in re.split(split_pattern, text, flags=re.MULTILINE):
            if not chunk.strip():
                continue
            splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=200)
            for piece in splitter.split_text(chunk):
                chunks.append(Document(page_content=piece, metadata=document.metadata))
        return chunks

    def _split_text(self, document: Document) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        return splitter.split_documents([document])

    def _split_documents(self, documents: list[Document]) -> list[Document]:
        chunks: list[Document] = []
        for document in documents:
            source = document.metadata.get("source", "")
            if source.endswith((".py", ".js")):
                chunks.extend(self._split_code(document))
            else:
                chunks.extend(self._split_text(document))
        return chunks

    def _get_mock_compatible_prompt(self) -> PromptTemplate:
        return PromptTemplate(
            input_variables=["context", "question"],
            template=(
                "Context:\n{context}\n\nQuestion: {question}\nHelpful Answer:"
            ),
        )

    def ingest_repository(self, repo_url: str, documents: list[Document]) -> int:
        if not documents:
            raise ValueError("No documents were provided for ingestion.")

        chunks = self._split_documents(documents)
        if not chunks:
            raise ValueError("No document chunks were created during ingestion.")

        embeddings = self.embedding_provider.get_embeddings()
        vector_store = FAISS.from_documents(chunks, embeddings)
        self.stores[repo_url] = vector_store
        self.chat_history[repo_url] = []
        return len(chunks)

    def query(self, repo_url: str, query: str) -> dict[str, Any]:
        if repo_url not in self.stores:
            raise ValueError("Repository has not been ingested yet. Please call /ingest-repo first.")

        retriever = self.stores[repo_url].as_retriever(search_kwargs={"k": 5})

        chain_kwargs = {}
        if getattr(self.llm, "_llm_type", "") == "enhanced-mock":
            chain_kwargs["prompt"] = self._get_mock_compatible_prompt()

        chain = RetrievalQA.from_chain_type(
            llm=self.llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs=chain_kwargs or None,
        )

        try:
            result = chain({"query": query})
        except Exception:
            source_documents = retriever.get_relevant_documents(query)
            sources = sorted({doc.metadata.get("source") for doc in source_documents if doc.metadata.get("source")})
            answer = self._summarize_documents_fallback(query, source_documents)
            self.chat_history.setdefault(repo_url, []).append({"question": query, "answer": answer})
            return {"answer": answer, "sources": sources, "history": self.chat_history[repo_url]}

        source_documents = result.get("source_documents", [])
        if source_documents is None:
            source_documents = []

        sources = []
        for doc in source_documents:
            source_name = doc.metadata.get("source")
            if source_name and source_name not in sources:
                sources.append(source_name)

        if isinstance(result, dict):
            answer = result.get("answer") or result.get("result") or str(result)
        else:
            answer = str(result)

        self.chat_history.setdefault(repo_url, []).append({"question": query, "answer": answer})
        return {"answer": answer, "sources": sources, "history": self.chat_history[repo_url]}