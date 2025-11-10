
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# S3 Configuration
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "anime-clips")
S3_REGION = os.getenv("S3_REGION", "us-east-1")

# Initialize S3 client
s3_client = boto3.client(
    's3',
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION,
    config=Config(signature_version='s3v4')
)


def ensure_bucket_exists():
    """Ensure the S3 bucket exists, create if not"""
    try:
        s3_client.head_bucket(Bucket=S3_BUCKET)
        logger.info(f"Bucket {S3_BUCKET} exists")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            logger.info(f"Creating bucket {S3_BUCKET}")
            s3_client.create_bucket(Bucket=S3_BUCKET)
        else:
            logger.error(f"Error checking bucket: {e}")
            raise


def generate_signed_upload_url(
    s3_key: str,
    content_type: str = "video/mp4",
    expires_in: int = 3600
) -> str:
    """
    Generate a pre-signed URL for uploading a file to S3
    
    Args:
        s3_key: S3 object key (path)
        content_type: MIME type of the file
        expires_in: URL expiration time in seconds
    
    Returns:
        Signed URL string
    """
    try:
        url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': s3_key,
                'ContentType': content_type
            },
            ExpiresIn=expires_in
        )
        logger.info(f"Generated upload URL for {s3_key}")
        return url
    except ClientError as e:
        logger.error(f"Error generating upload URL: {e}")
        raise


def generate_signed_download_url(
    s3_key: str,
    expires_in: int = 86400
) -> str:
    """
    Generate a pre-signed URL for downloading a file from S3
    
    Args:
        s3_key: S3 object key (path)
        expires_in: URL expiration time in seconds (default: 24 hours)
    
    Returns:
        Signed URL string
    """
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': s3_key
            },
            ExpiresIn=expires_in
        )
        logger.info(f"Generated download URL for {s3_key}")
        return url
    except ClientError as e:
        logger.error(f"Error generating download URL: {e}")
        raise


def upload_to_s3(
    local_path: str,
    s3_key: str,
    content_type: Optional[str] = None
) -> str:
    """
    Upload a file from local path to S3
    
    Args:
        local_path: Local file path
        s3_key: S3 object key (destination path)
        content_type: Optional MIME type
    
    Returns:
        S3 URL of uploaded file
    """
    try:
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type
        
        s3_client.upload_file(
            local_path,
            S3_BUCKET,
            s3_key,
            ExtraArgs=extra_args
        )
        
        logger.info(f"Uploaded {local_path} to s3://{S3_BUCKET}/{s3_key}")
        
        # Return S3 URL
        return f"s3://{S3_BUCKET}/{s3_key}"
    
    except ClientError as e:
        logger.error(f"Error uploading to S3: {e}")
        raise


def download_from_s3(s3_url: str, local_path: str):
    """
    Download a file from S3 to local path
    
    Args:
        s3_url: S3 URL (s3://bucket/key or just the key)
        local_path: Local destination path
    """
    try:
        # Parse S3 URL
        if s3_url.startswith('s3://'):
            # Extract key from s3://bucket/key format
            parts = s3_url.replace('s3://', '').split('/', 1)
            bucket = parts[0]
            s3_key = parts[1] if len(parts) > 1 else ''
        else:
            # Assume it's just the key
            bucket = S3_BUCKET
            s3_key = s3_url
        
        # Ensure local directory exists
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # Download file
        s3_client.download_file(bucket, s3_key, local_path)
        logger.info(f"Downloaded {s3_url} to {local_path}")
    
    except ClientError as e:
        logger.error(f"Error downloading from S3: {e}")
        raise


def delete_from_s3(s3_url: str):
    """
    Delete a file from S3
    
    Args:
        s3_url: S3 URL (s3://bucket/key or just the key)
    """
    try:
        # Parse S3 URL
        if s3_url.startswith('s3://'):
            parts = s3_url.replace('s3://', '').split('/', 1)
            bucket = parts[0]
            s3_key = parts[1] if len(parts) > 1 else ''
        else:
            bucket = S3_BUCKET
            s3_key = s3_url
        
        s3_client.delete_object(Bucket=bucket, Key=s3_key)
        logger.info(f"Deleted {s3_url}")
    
    except ClientError as e:
        logger.error(f"Error deleting from S3: {e}")
        raise


def delete_folder_from_s3(s3_prefix: str):
    """
    Delete all objects with a given prefix (folder) from S3
    
    Args:
        s3_prefix: S3 key prefix (folder path)
    """
    try:
        # List all objects with prefix
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=S3_BUCKET, Prefix=s3_prefix)
        
        delete_keys = []
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    delete_keys.append({'Key': obj['Key']})
        
        # Delete objects in batches
        if delete_keys:
            for i in range(0, len(delete_keys), 1000):  # S3 limit is 1000 per request
                batch = delete_keys[i:i+1000]
                s3_client.delete_objects(
                    Bucket=S3_BUCKET,
                    Delete={'Objects': batch}
                )
            logger.info(f"Deleted {len(delete_keys)} objects with prefix {s3_prefix}")
    
    except ClientError as e:
        logger.error(f"Error deleting folder from S3: {e}")
        raise


def list_files(s3_prefix: str, max_keys: int = 1000) -> list:
    """
    List files in S3 with a given prefix
    
    Args:
        s3_prefix: S3 key prefix (folder path)
        max_keys: Maximum number of keys to return
    
    Returns:
        List of S3 object keys
    """
    try:
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=s3_prefix,
            MaxKeys=max_keys
        )
        
        if 'Contents' not in response:
            return []
        
        return [obj['Key'] for obj in response['Contents']]
    
    except ClientError as e:
        logger.error(f"Error listing files from S3: {e}")
        raise


def get_file_size(s3_key: str) -> int:
    """
    Get the size of a file in S3
    
    Args:
        s3_key: S3 object key
    
    Returns:
        File size in bytes
    """
    try:
        response = s3_client.head_object(Bucket=S3_BUCKET, Key=s3_key)
        return response['ContentLength']
    except ClientError as e:
        logger.error(f"Error getting file size: {e}")
        raise


def file_exists(s3_key: str) -> bool:
    """
    Check if a file exists in S3
    
    Args:
        s3_key: S3 object key
    
    Returns:
        True if file exists, False otherwise
    """
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=s3_key)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        logger.error(f"Error checking file existence: {e}")
        raise


def copy_file(source_key: str, dest_key: str):
    """
    Copy a file within S3
    
    Args:
        source_key: Source S3 object key
        dest_key: Destination S3 object key
    """
    try:
        copy_source = {'Bucket': S3_BUCKET, 'Key': source_key}
        s3_client.copy_object(
            CopySource=copy_source,
            Bucket=S3_BUCKET,
            Key=dest_key
        )
        logger.info(f"Copied {source_key} to {dest_key}")
    except ClientError as e:
        logger.error(f"Error copying file: {e}")
        raise


# Initialize bucket on module import
try:
    ensure_bucket_exists()
except Exception as e:
    logger.warning(f"Could not ensure bucket exists (may be running tests): {e}")
