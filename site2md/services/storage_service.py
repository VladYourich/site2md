from site2md.core.logging import get_logger
from site2md.domain.ports import StoragePort
from site2md.storage.filesystem import FilesystemStorage

logger = get_logger(__name__)


class StorageService:
    def __init__(self, backend: StoragePort | None = None):
        self.backend = backend or FilesystemStorage()

    async def store_result(self, job_id: str, markdown: str, job_metadata: dict) -> str:
        metadata = {
            "job_id": job_id,
            "created_at": job_metadata.get("created_at", ""),
            "completed_at": job_metadata.get("completed_at", ""),
            "url": job_metadata.get("url", ""),
            "pages_crawled": job_metadata.get("pages_crawled", 0),
            "status": job_metadata.get("status", ""),
        }
        return await self.backend.store_result(job_id, markdown, metadata)

    async def read_result(self, job_id: str) -> str | None:
        return await self.backend.read_result(job_id)
