"""File storage (Rx photos, PDFs) through the S3 API only, so the store can move
from SeaweedFS (docker-compose) to cloud S3 by changing settings:

    S3_ENDPOINT   where services reach it (http://seaweedfs:8333, internal network only)
    S3_BUCKET     private bucket (rx-files)
    S3_ACCESS_KEY / S3_SECRET_KEY

Rules:
- The bucket is private and the store is never reachable from outside: no host
  port, no Traefik route, no presigned or public links. Browsers get files only
  through the owning service, which checks the user, the branch and the
  permission and writes the audit entry on every request (see prescription).
- Objects get random keys; the original file name lives only in the database.
- No delete: records are never deleted, so neither are their files.
Needs aioboto3 (`pharmacy-shared[storage]`).
"""

from dataclasses import dataclass
from typing import Any

import aioboto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .errors import AppError, ErrorCode


def _unavailable(exc: Exception) -> AppError:
    return AppError(ErrorCode.TEMPORARILY_UNAVAILABLE, "The file store is not reachable; try again",
                    status_code=503, details={"error": type(exc).__name__})  # fmt: skip


@dataclass(frozen=True)
class Storage:
    endpoint: str
    bucket: str
    access_key: str
    secret_key: str
    region: str = "us-east-1"

    @classmethod
    def from_settings(cls, settings: Any) -> "Storage":
        return cls(
            endpoint=settings.s3_endpoint,
            bucket=settings.s3_bucket,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
        )

    def _client(self):  # noqa: ANN202
        return aioboto3.Session().client(
            "s3", endpoint_url=self.endpoint, aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key, region_name=self.region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          connect_timeout=3, read_timeout=15, retries={"max_attempts": 2}),
        )  # fmt: skip

    async def ensure_bucket(self) -> None:
        """Create the bucket if missing (private: no policy, no public ACL)."""
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self.bucket)
            except ClientError:
                await s3.create_bucket(Bucket=self.bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            async with self._client() as s3:
                await s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise _unavailable(exc) from exc

    async def get(self, key: str) -> bytes:
        """A missing object → NOT_FOUND; the store down → TEMPORARILY_UNAVAILABLE."""
        try:
            async with self._client() as s3:
                obj = await s3.get_object(Bucket=self.bucket, Key=key)
                return await obj["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise AppError(ErrorCode.NOT_FOUND, "File not found", status_code=404) from exc
            raise _unavailable(exc) from exc
        except (BotoCoreError, OSError) as exc:
            raise _unavailable(exc) from exc
