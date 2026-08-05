"""
pipeline/connectors/s3.py
==========================
Object Storage Client for AWS S3 and Cloudflare R2.
Handles uploading data files (Parquet) and media assets (WebP/MP3).
"""
from __future__ import annotations
import logging
from botocore.config import Config
import boto3
from pipeline.settings import settings

logger = logging.getLogger(__name__)

class S3Connector:
    """Manages secure reads, writes, and uploads to S3-compatible cloud storage."""

    def __init__(self):
        self.bucket = settings.s3_bucket_name
        self.cdn_domain = settings.s3_cdn_domain
        
        access_key = settings.s3_access_key()
        secret_key = settings.s3_secret_key()
        endpoint = settings.s3_endpoint_url
        
        if access_key and secret_key:
            logger.info("Initializing S3 client with endpoint: %s", endpoint)
            self.client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(signature_version="s3v4")
            )
        else:
            logger.warning("Object Storage credentials missing. S3Connector will run in local mockup mode.")
            self.client = None

    def upload_file(self, local_path: str, s3_key: str, content_type: str | None = None) -> str:
        """Uploads a local file to S3/R2 and returns the public CDN URL."""
        if not self.client:
            logger.info("[Mock S3] Simulating upload of %s to s3://%s/%s", local_path, self.bucket, s3_key)
            return f"{self.cdn_domain.rstrip('/')}/{s3_key.lstrip('/')}"
            
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
            
        try:
            self.client.upload_file(
                local_path,
                self.bucket,
                s3_key,
                ExtraArgs=extra_args
            )
            logger.info("Successfully uploaded %s to s3://%s/%s", local_path, self.bucket, s3_key)
            return f"{self.cdn_domain.rstrip('/')}/{s3_key.lstrip('/')}"
        except Exception as e:
            logger.error("Failed to upload %s to S3: %s", local_path, str(e))
            raise

    def generate_presigned_url(self, s3_key: str, expiration: int = 3600) -> str:
        """Generates a secure presigned URL for private asset retrieval."""
        if not self.client:
            return f"{self.cdn_domain.rstrip('/')}/{s3_key.lstrip('/')}"
            
        try:
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": s3_key},
                ExpiresIn=expiration
            )
            return url
        except Exception as e:
            logger.error("Failed to generate presigned URL for %s: %s", s3_key, str(e))
            raise
