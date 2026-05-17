import json
import uuid

import redis.asyncio as redis

from site2md.config import settings
from site2md.core.logging import get_logger
from site2md.domain.models import CrawlJob
from site2md.models.schemas import CrawlStatus

logger = get_logger(__name__)


class CrawlService:
    class NotFoundError(Exception):
        pass

    class JobNotCompleted(Exception):
        pass

    class ResultExpired(Exception):
        pass

    class JobAlreadyCompleted(Exception):
        pass

    class JobAlreadyCancelled(Exception):
        pass

    def __init__(self, redis_client: redis.Redis):
        self.r = redis_client

    def _metadata_key(self, job_id: str) -> str:
        return f"crawl:{job_id}:metadata"

    async def job_exists(self, job_id: str) -> bool:
        return await self.r.exists(self._metadata_key(job_id)) > 0

    async def create_crawl(
        self,
        url: str,
        max_depth: int = 3,
        render_js: bool = False,
        chunk_delimiter: str = "\n><\n",
    ) -> CrawlJob:
        job_id = str(uuid.uuid4())
        job = CrawlJob(
            job_id=job_id,
            url=url,
            max_depth=max_depth,
            render_js=render_js,
            chunk_delimiter=chunk_delimiter,
        )
        data = {
            "url": job.url,
            "status": job.status.value,
            "max_depth": job.max_depth,
            "render_js": str(job.render_js).lower(),
            "chunk_delimiter": job.chunk_delimiter,
            "pages_crawled": job.pages_crawled,
            "pages_total": "",
            "created_at": job.created_at.isoformat(),
            "started_at": "",
            "completed_at": "",
            "error": "",
            "result_path": "",
            "failed_urls": json.dumps([]),
        }
        key = self._metadata_key(job_id)
        await self.r.hset(key, mapping=data)
        await self.r.expire(key, settings.result_ttl_hours * 3600)
        await self.r.lpush("arq:queue", json.dumps({
            "job_id": job_id,
            "url": url,
            "max_depth": max_depth,
            "render_js": render_js,
            "chunk_delimiter": chunk_delimiter,
        }))
        logger.info("Crawl job created", extra={"job_id": job_id, "url": url})
        return job

    async def get_status(self, job_id: str) -> CrawlStatus:
        key = self._metadata_key(job_id)
        if not await self.r.exists(key):
            raise self.NotFoundError()
        data = await self.r.hgetall(key)
        def decode(v: bytes) -> str:
            return v.decode() if v else ""

        return CrawlStatus(
            job_id=job_id,
            status=decode(data.get(b"status", b"")),
            url=decode(data.get(b"url", b"")),
            pages_crawled=int(decode(data.get(b"pages_crawled", b"0")) or 0),
            pages_total=None if not decode(data.get(b"pages_total", b"")) else int(decode(data.get(b"pages_total", b""))),
            created_at=decode(data.get(b"created_at", b"")),
            started_at=decode(data.get(b"started_at", b"")) or None,
            completed_at=decode(data.get(b"completed_at", b"")) or None,
            error=decode(data.get(b"error", b"")) or None,
            failed_urls=json.loads(decode(data.get(b"failed_urls", b"[]"))),
        )

    async def get_result(self, job_id: str) -> str:
        key = self._metadata_key(job_id)
        if not await self.r.exists(key):
            raise self.NotFoundError()
        data = await self.r.hgetall(key)
        def decode(v: bytes) -> str:
            return v.decode() if v else ""

        status = decode(data.get(b"status", b""))
        if status in ("pending", "running"):
            raise self.JobNotCompleted()
        result_path = decode(data.get(b"result_path", b""))
        if not result_path:
            raise self.ResultExpired()
        import os
        if not os.path.exists(result_path):
            raise self.ResultExpired()
        with open(result_path) as f:
            return f.read()

    async def cancel_crawl(self, job_id: str) -> None:
        key = self._metadata_key(job_id)
        if not await self.r.exists(key):
            raise self.NotFoundError()
        data = await self.r.hgetall(key)
        def decode(v: bytes) -> str:
            return v.decode() if v else ""

        status = decode(data.get(b"status", b""))
        if status in ("completed", "completed_with_errors", "failed"):
            raise self.JobAlreadyCompleted()
        if status == "cancelled":
            raise self.JobAlreadyCancelled()

        await self.r.hset(key, "status", "cancelled")
        await self.r.set(f"crawl:{job_id}:cancel", "1")
        logger.info("Crawl job cancelled", extra={"job_id": job_id})

    async def update_progress(self, job_id: str, pages_crawled: int) -> None:
        key = self._metadata_key(job_id)
        await self.r.hset(key, "pages_crawled", str(pages_crawled))
        event = json.dumps({
            "job_id": job_id,
            "pages_crawled": pages_crawled,
        })
        await self.r.publish(f"crawl:{job_id}:progress", event)
