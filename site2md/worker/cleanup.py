from site2md.config import settings
from site2md.core.logging import get_logger
from site2md.storage.filesystem import FilesystemStorage

logger = get_logger(__name__)


async def cleanup_expired_results() -> None:
    storage = FilesystemStorage()
    ttl = settings.result_ttl_hours
    expired = await storage.list_expired(ttl)
    for job_id in expired:
        await storage.delete_result(job_id)
    if expired:
        logger.info("Cleanup completed", extra={"deleted_count": len(expired)})
