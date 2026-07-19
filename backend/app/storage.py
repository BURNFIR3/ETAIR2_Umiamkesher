import io
import hashlib
from typing import Optional
from minio import Minio
from minio.error import S3Error

from app.config import settings

_client: Optional[Minio] = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        endpoint = settings.MINIO_ENDPOINT
        secure = settings.MINIO_SECURE
        # Automatically strip http:// or https:// if included (e.g. from Supabase S3 URLs)
        if endpoint.startswith("https://"):
            endpoint = endpoint[8:]
            secure = True
        elif endpoint.startswith("http://"):
            endpoint = endpoint[7:]

        if ".supabase.co" in endpoint or "amazonaws.com" in endpoint or "r2.cloudflarestorage.com" in endpoint:
            secure = True

        _client = Minio(
            endpoint,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=secure,
            region=getattr(settings, "MINIO_REGION", "us-east-1"),
        )
    return _client


def upload_file(
    file_data: bytes,
    object_key: str,
    content_type: str,
    bucket: Optional[str] = None,
) -> str:
    """Upload bytes to MinIO. Returns the object key."""
    client = get_minio_client()
    bucket = bucket or settings.MINIO_BUCKET_FILES
    client.put_object(
        bucket,
        object_key,
        io.BytesIO(file_data),
        length=len(file_data),
        content_type=content_type,
    )
    return object_key


def download_file(object_key: str, bucket: Optional[str] = None) -> bytes:
    """Download file bytes from MinIO."""
    client = get_minio_client()
    bucket = bucket or settings.MINIO_BUCKET_FILES
    response = client.get_object(bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def get_presigned_url(
    object_key: str,
    bucket: Optional[str] = None,
    expires_seconds: int = 3600,
) -> str:
    """Generate a presigned URL for temporary direct access."""
    from datetime import timedelta
    client = get_minio_client()
    bucket = bucket or settings.MINIO_BUCKET_FILES
    return client.presigned_get_object(bucket, object_key, expires=timedelta(seconds=expires_seconds))


def delete_file(object_key: str, bucket: Optional[str] = None) -> None:
    client = get_minio_client()
    bucket = bucket or settings.MINIO_BUCKET_FILES
    client.remove_object(bucket, object_key)


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_storage_key(workspace_id: str, document_id: str, version: int, filename: str) -> str:
    """Deterministic, organized storage key."""
    return f"workspaces/{workspace_id}/documents/{document_id}/v{version}/{filename}"
