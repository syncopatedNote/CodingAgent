import logging
import uuid

import boto3
from botocore.exceptions import ClientError

try:
    # Worker context: full monorepo at /app, RAG package importable as RAG.*
    from RAG.settings import rag_settings
except ImportError:
    # RAG service context: flat layout where settings.py is at /app/settings.py
    from settings import rag_settings  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

# CORS policy applied to the S3 bucket at startup so browsers can POST
# directly to S3 from any origin. Tighten AllowedOrigins in production.
_BUCKET_CORS_RULES = [
    {
        "AllowedOrigins": ["*"],
        "AllowedMethods": ["POST", "PUT", "GET"],
        "AllowedHeaders": ["*"],
        "MaxAgeSeconds": 3000,
    }
]


def _get_s3_client():
    return boto3.client(
        "s3",
        region_name=rag_settings.aws_region,
        aws_access_key_id=rag_settings.aws_access_key_id,
        aws_secret_access_key=rag_settings.aws_secret_access_key,
    )


def ensure_bucket_cors() -> None:
    """
    Apply the required CORS policy to the S3 bucket.
    Called once at service startup. Safe to call repeatedly (idempotent).
    """
    try:
        _get_s3_client().put_bucket_cors(
            Bucket=rag_settings.s3_bucket_name,
            CORSConfiguration={"CORSRules": _BUCKET_CORS_RULES},
        )
        logger.info(
            "S3 bucket CORS policy applied to bucket: %s",
            rag_settings.s3_bucket_name,
        )
    except ClientError:
        logger.error(
            "Failed to apply CORS policy to S3 bucket — uploads may be blocked by browsers.",
            exc_info=True,
        )


def generate_presigned_post(filename: str, content_type: str) -> dict:
    """
    Generate an S3 presigned POST so the browser can upload directly to S3.

    Returns:
        url        — POST target URL
        fields     — form fields to include in the multipart POST body
        object_key — S3 key assigned to the file (pass this back to the
                     ingest API once the upload completes)
    """
    object_key = f"uploads/{uuid.uuid4()}/{filename}"

    s3_client = _get_s3_client()

    try:
        presigned = s3_client.generate_presigned_post(
            Bucket=rag_settings.s3_bucket_name,
            Key=object_key,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}],
            ExpiresIn=rag_settings.presigned_url_expiry_seconds,
        )
    except ClientError:
        logger.error("Failed to generate presigned POST URL", exc_info=True)
        raise

    return {
        "url": presigned["url"],
        "fields": presigned["fields"],
        "object_key": object_key,
    }


def verify_object_exists(bucket: str, key: str) -> dict:
    """Head the object to verify it exists and return metadata.

    Raises ClientError if the object does not exist or is not accessible.
    """
    try:
        resp = _get_s3_client().head_object(Bucket=bucket, Key=key)
        logger.info("S3 object verified: %s/%s", bucket, key)
        return resp
    except ClientError:
        logger.exception("S3 head_object failed for %s/%s", bucket, key)
        raise


def download_object_to_file(bucket: str, key: str, dest_path: str) -> None:
    """Download an S3 object to a local file path.

    Uses streaming download to avoid loading the whole object in memory.
    """
    try:
        s3 = _get_s3_client()
        with open(dest_path, "wb") as f:
            s3.download_fileobj(Bucket=bucket, Key=key, Fileobj=f)
        logger.info("Downloaded s3://%s/%s to %s", bucket, key, dest_path)
    except ClientError:
        logger.exception("Failed to download s3://%s/%s", bucket, key)
        raise


def download_object_bytes(bucket: str, key: str) -> bytes:
    """Return the raw bytes of an S3 object.

    Convenience helper for small objects.
    """
    try:
        resp = _get_s3_client().get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
    except ClientError:
        logger.exception("Failed to read s3://%s/%s", bucket, key)
        raise
