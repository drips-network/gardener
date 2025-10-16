"""
S3-compatible object storage helpers
"""

import hashlib

import boto3
from botocore.config import Config

from services.shared.config import settings


def _make_s3_client():
    """
    Build a boto3 S3 client for MinIO and S3-compatible endpoints

    Returns:
        boto3 S3 client
    """
    address_style = "path" if settings.object_storage.FORCE_PATH_STYLE else "auto"
    config_kwargs = {"signature_version": "s3v4"}
    if address_style == "path":
        config_kwargs["s3"] = {"addressing_style": "path"}
    client_config = Config(**config_kwargs)
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage.ENDPOINT_URL,
        aws_access_key_id=settings.object_storage.ACCESS_KEY,
        aws_secret_access_key=settings.object_storage.SECRET_KEY,
        region_name=settings.object_storage.REGION,
        config=client_config,
    )


def upload_bytes(bucket, object_key, data_bytes, content_type, metadata=None):
    """
    Upload a bytes payload to object storage

    Args:
        bucket (str): Target bucket name
        object_key (str): Object key within the bucket
        data_bytes (bytes): Serialized payload to upload
        content_type (str): MIME type for the object
        metadata (dict|None): Optional object metadata

    Returns:
        dict: Upload metadata including checksums and etag
    """
    client = _make_s3_client()

    md5_hex = hashlib.md5(data_bytes).hexdigest()
    sha256_hex = hashlib.sha256(data_bytes).hexdigest()

    extra_args = {"ContentType": content_type, "Metadata": metadata or {}}
    response = client.put_object(Bucket=bucket, Key=object_key, Body=data_bytes, **extra_args)

    return {
        "etag": (response.get("ETag") or "").strip('"'),
        "version_id": response.get("VersionId"),
        "size_bytes": len(data_bytes),
        "checksum_md5": md5_hex,
        "checksum_sha256": sha256_hex,
    }
