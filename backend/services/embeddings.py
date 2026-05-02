import os

from langchain.embeddings import OpenAIEmbeddings


class EmbeddingProvider:
    def __init__(self, model_name: str | None = None) -> None:
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.model_name = model_name or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.embeddings = self._create_embedding_client()

    def _create_embedding_client(self):
        if self.openai_key:
            try:
                return OpenAIEmbeddings(model=self.model_name, api_key=self.openai_key)
            except Exception as exc:
                raise RuntimeError(
                    "Failed to initialize OpenAI embeddings. "
                    "Verify your OPENAI_API_KEY and package versions."
                ) from exc

        try:
            from langchain.embeddings.huggingface import HuggingFaceEmbeddings
        except ImportError as exc:
            raise ImportError(
                "HuggingFace embeddings require sentence-transformers. "
                "Install it with `pip install sentence-transformers`."
            ) from exc

        return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

    def get_embeddings(self):
        return self.embeddings