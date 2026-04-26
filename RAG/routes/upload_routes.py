import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.s3_service import generate_presigned_post, verify_object_exists

from redis import Redis
from rq import Queue
from rq.job import Job

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/upload", tags=["Upload"])


ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class PresignedUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str


class PresignedUrlResponse(BaseModel):
    url: str
    fields: dict
    object_key: str


@router.post("/presigned-url", response_model=PresignedUrlResponse)
async def get_presigned_url(request: PresignedUrlRequest) -> PresignedUrlResponse:
    """
    Request a presigned S3 POST URL for a file upload.

    The client should:
      1. POST this endpoint with filename + content_type.
      2. Use the returned url + fields to POST the file directly to S3
         (multipart/form-data — fields first, then the file under key "file").
      3. Pass object_key back to the ingest endpoint once upload completes.
    """
    if request.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported content type. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )

    try:
        result = generate_presigned_post(request.filename, request.content_type)
    except Exception:
        logger.error("Presigned URL generation failed", exc_info=True)
        raise HTTPException(status_code=502, detail="Could not generate upload URL.")

    return PresignedUrlResponse(**result)


class UploadCompleteRequest(BaseModel):
    object_key: str = Field(..., min_length=1)
    bucket: Optional[str] = None
    etag: Optional[str] = None
    size: Optional[int] = None


@router.post("/complete")
async def upload_complete(request: UploadCompleteRequest):
    """Called by the frontend after a successful S3 upload.

    Verifies the object exists in S3, enqueues an ingestion job and
    returns a job id the client can poll.
    """
    bucket = request.bucket or os.getenv("S3_BUCKET_NAME")
    if not bucket:
        raise HTTPException(status_code=400, detail="Bucket not provided")

    try:
        verify_object_exists(bucket, request.object_key)
    except Exception:
        logger.error("Uploaded object not found: %s/%s", bucket, request.object_key)
        raise HTTPException(status_code=404, detail="Uploaded object not found")

    # Enqueue ingestion job using RQ + Redis
    redis_url = os.getenv("RAG_REDIS_URL", "redis://redis:6379/0")
    redis_conn = Redis.from_url(redis_url)
    q = Queue(connection=redis_conn)

    # Enqueue the ingest task by import path. The worker image must include
    # the full repo so it can import `RAG.ingest.ingest_file` when executing.
    job = q.enqueue(
        "RAG.ingest.ingest_file", bucket, request.object_key, job_timeout=3600
    )

    return {"job_id": job.id, "status_url": f"/upload/status/{job.id}"}


@router.get("/status/{job_id}")
async def upload_status(job_id: str):
    redis_url = os.getenv("RAG_REDIS_URL", "redis://redis:6379/0")
    redis_conn = Redis.from_url(redis_url)
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": job.get_status(),
        "result": job.result if job.is_finished else None,
        "exc_info": job.exc_info,
    }
