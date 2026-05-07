import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class S3Client:
    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str):
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )

    def upload_bytes(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        logger.debug("Uploaded s3://%s/%s", self._bucket, key)
        return f"{self._client.meta.endpoint_url}/{self._bucket}/{key}"

    def download_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def object_exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False
