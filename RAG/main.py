import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.upload_routes import router as upload_router
from services.s3_service import ensure_bucket_cors

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RAG upload service starting")
    ensure_bucket_cors()
    yield
    logger.info("RAG upload service shutting down")


app = FastAPI(
    title="RAG Upload Service",
    description="Handles presigned S3 URLs for direct browser-to-S3 file uploads.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to specific frontend origin in production
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(upload_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
