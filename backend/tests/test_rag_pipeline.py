import unittest

from langchain.chains.question_answering.stuff_prompt import PROMPT

from backend.services.rag_pipeline import RAGPipeline


class RAGPipelineMockFallbackTests(unittest.TestCase):
    def test_mock_llm_extracts_context_from_default_retrievalqa_prompt(self):
        llm = RAGPipeline.__new__(RAGPipeline)._create_mock_llm()
        prompt = PROMPT.format(
            context="The service stores indexes in memory.",
            question="Where are indexes stored?",
        )

        answer = llm._call(prompt)

        self.assertIn("indexes", answer.lower())
        self.assertNotIn("don't have any context", answer.lower())


if __name__ == "__main__":
    unittest.main()
