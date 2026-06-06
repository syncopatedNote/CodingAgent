import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.s3_service import generate_presigned_post, verify_object_exists

from temporalio.client import Client
from workflows.ingestion_workflow import IngestionWorkflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["Upload"])

_temporal_client: Optional[Client] = None
_active_handles: dict[str, Any] = {}  # activity_id -> ActivityHandle

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


async def _get_client() -> Client:
    global _temporal_client
    if _temporal_client is None:
        temporal_host = os.getenv("TEMPORAL_HOST", "temporal:7233")
        _temporal_client = await Client.connect(temporal_host)
    return _temporal_client


class PresignedUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str


class PresignedUrlResponse(BaseModel):
    url: str
    fields: dict
    object_key: str


@router.post("/presigned-url", response_model=PresignedUrlResponse)
async def get_presigned_url(
    request: PresignedUrlRequest,
) -> PresignedUrlResponse:
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
            detail=(
                f"Unsupported content type. "
                f"Allowed: {sorted(ALLOWED_CONTENT_TYPES)}"
            ),
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

    Fires a standalone Temporal activity and immediately returns the activity
    id. The actual ingestion runs on rag-worker — this service does not wait.
    """
    bucket = request.bucket or os.getenv("S3_BUCKET_NAME")
    if not bucket:
        raise HTTPException(status_code=400, detail="Bucket not provided")

    try:
        verify_object_exists(bucket, request.object_key)
    except Exception:
        logger.error("Uploaded object not found: %s/%s", bucket, request.object_key)
        raise HTTPException(status_code=404, detail="Uploaded object not found")

    client = await _get_client()
    workflow_id = f"ingest-{request.object_key}"

    handle = await client.start_workflow(
        IngestionWorkflow.run,
        args=[bucket, request.object_key],
        id=workflow_id,
        task_queue="rag-ingestion",
    )

    # Store the handle for status queries — no waiting here.
    _active_handles[workflow_id] = handle
    return {
        "job_id": workflow_id,
        "status_url": f"/upload/status/{workflow_id}",
    }


@router.get("/status/{job_id}")
async def upload_status(job_id: str):
    """Non-blocking status check — describe() is a quick server query."""
    handle = _active_handles.get(job_id)
    if handle is None:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        desc = await handle.describe()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    raw = str(desc.status).lower()
    if "completed" in raw:
        status = "finished"
    elif any(s in raw for s in ("failed", "timed_out", "canceled")):
        status = "failed"
    else:
        status = "started"

    return {
        "job_id": job_id,
        "status": status,
        "result": None,
        "exc_info": None,
    }
