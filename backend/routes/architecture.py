from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from backend.services.architecture_explorer import ArchitectureExplorer
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class ArchitectureRequest(BaseModel):
    repo_url: HttpUrl


class ArchitectureResponse(BaseModel):
    repo_name: str
    status: str
    warnings: list[str]
    languages: list[dict[str, Any]]
    frameworks: list[dict[str, Any]]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


@router.post("/architecture", response_model=ArchitectureResponse)
def analyze_architecture(request: ArchitectureRequest):
    try:
        result = ArchitectureExplorer().analyze(str(request.repo_url))
    except ValueError as exc:
        logger.info("Architecture analysis rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning("GitHub architecture analysis failed: %s", exc)
        status_code = 429 if "rate limit" in str(exc).lower() else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Architecture analysis failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during architecture analysis.",
        ) from exc
    return ArchitectureResponse(**result)
