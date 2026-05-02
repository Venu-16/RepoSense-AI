from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl
from backend.services.rag_pipeline import RAGPipeline
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class QueryRequest(BaseModel):
    repo_url: HttpUrl
    query: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
    history: list[dict[str, str]]


@router.post("/query", response_model=QueryResponse)
async def query_repository(request: QueryRequest):
    pipeline = RAGPipeline.get_instance()
    try:
        result = pipeline.query(str(request.repo_url), request.query)
    except ValueError as exc:
        logger.error("Query failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        logger.error("LLM pipeline error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.error("Query failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred while querying the repository.")

    return QueryResponse(
        answer=result["answer"],
        sources=result["sources"],
        history=result["history"],
    )