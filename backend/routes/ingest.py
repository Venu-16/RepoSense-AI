from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl
from backend.services.github_loader import GitHubRepositoryLoader
from backend.services.rag_pipeline import RAGPipeline
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class IngestRequest(BaseModel):
    repo_url: HttpUrl


class IngestResponse(BaseModel):
    repo_url: str
    repo_name: str
    indexed_files: int
    indexed_chunks: int
    sources: list[str]


@router.post("/ingest-repo", response_model=IngestResponse)
async def ingest_repo(request: IngestRequest):
    loader = GitHubRepositoryLoader()
    try:
        documents = loader.load_repository(str(request.repo_url))
    except ValueError as exc:
        logger.error("Repository ingestion failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))

    if not documents:
        raise HTTPException(status_code=400, detail="No supported files were found in the repository.")

    pipeline = RAGPipeline.get_instance()
    try:
        indexed_chunks = pipeline.ingest_repository(str(request.repo_url), documents)
    except RuntimeError as exc:
        logger.error("Repository ingestion failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.error("Repository ingestion failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred during ingestion.")

    sources = sorted({doc.metadata.get("source") for doc in documents})
    return IngestResponse(
        repo_url=str(request.repo_url),
        repo_name=loader.get_repo_name(str(request.repo_url)),
        indexed_files=len(sources),
        indexed_chunks=indexed_chunks,
        sources=sources,
    )