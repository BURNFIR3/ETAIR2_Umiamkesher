import io
import hashlib
from typing import Optional
import boto3
from botocore.client import Config

from app.config import settings

_client = None

def get_s3_client():
    global _client
    if _client is None:
        endpoint = settings.MINIO_ENDPOINT
        secure = settings.MINIO_SECURE
        
        # Ensure endpoint has http:// or https:// for boto3
        if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
            if secure or ".supabase.co" in endpoint or "amazonaws.com" in endpoint or "r2.cloudflarestorage.com" in endpoint:
                endpoint = f"https://{endpoint}"
            else:
                endpoint = f"http://{endpoint}"
                
        _client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name=getattr(settings, "MINIO_REGION", "us-east-1"),
            config=Config(signature_version="s3v4")
        )
    return _client

def upload_file(
    file_data: bytes,
    object_key: str,
    content_type: str,
    bucket: Optional[str] = None,
) -> str:
    """Upload bytes to S3. Returns the object key."""
    client = get_s3_client()
    bucket = bucket or settings.MINIO_BUCKET_FILES
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=file_data,
        ContentType=content_type,
    )
    return object_key

def download_file(object_key: str, bucket: Optional[str] = None) -> bytes:
    """Download file bytes from S3."""
    client = get_s3_client()
    bucket = bucket or settings.MINIO_BUCKET_FILES
    response = client.get_object(Bucket=bucket, Key=object_key)
    return response['Body'].read()

def get_presigned_url(
    object_key: str,
    bucket: Optional[str] = None,
    expires_seconds: int = 3600,
) -> str:
    """Generate a presigned URL for temporary direct access."""
    client = get_s3_client()
    bucket = bucket or settings.MINIO_BUCKET_FILES
    return client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': object_key},
        ExpiresIn=expires_seconds
    )

def delete_file(object_key: str, bucket: Optional[str] = None) -> None:
    client = get_s3_client()
    bucket = bucket or settings.MINIO_BUCKET_FILES
    client.delete_object(Bucket=bucket, Key=object_key)

def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def build_storage_key(workspace_id: str, document_id: str, version: int, filename: str) -> str:
    """Deterministic, organized storage key."""
    return f"workspaces/{workspace_id}/documents/{document_id}/v{version}/{filename}"
