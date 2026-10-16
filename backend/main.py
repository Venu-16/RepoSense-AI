import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routes.architecture import router as architecture_router
from backend.routes.ingest import router as ingest_router
from backend.routes.query import router as query_router

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)

app = FastAPI(
    title="RepoSense AI",
    description="A Retrieval-Augmented Generation backend for chatting with GitHub repositories.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router, prefix="/api", tags=["ingestion"])
app.include_router(query_router, prefix="/api", tags=["query"])
app.include_router(architecture_router, prefix="/api", tags=["architecture"])


@app.get("/")
async def root():
    return {"message": "RepoSense AI backend is running."}