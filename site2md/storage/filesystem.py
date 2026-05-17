import json
import shutil
from pathlib import Path

from site2md.config import settings
from site2md.core.logging import get_logger
from site2md.domain.ports import StoragePort

logger = get_logger(__name__)


class FilesystemStorage(StoragePort):
    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or settings.storage_path)

    def _job_dir(self, job_id: str) -> Path:
        return self.base_path / job_id

    async def store_result(self, job_id: str, markdown_content: str, metadata: dict) -> str:
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)

        result_path = job_dir / "done.md"
        tmp_path = job_dir / "done.md.tmp"
        tmp_path.write_text(markdown_content, encoding="utf-8")
        tmp_path.rename(result_path)

        meta_path = job_dir / "metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")

        logger.info("Result stored", extra={"job_id": job_id, "path": str(result_path)})
        return str(result_path)

    async def read_result(self, job_id: str) -> str | None:
        result_path = self._job_dir(job_id) / "done.md"
        if not result_path.exists():
            return None
        return result_path.read_text(encoding="utf-8")

    async def delete_result(self, job_id: str) -> bool:
        job_dir = self._job_dir(job_id)
        if job_dir.exists():
            shutil.rmtree(job_dir)
            logger.info("Result deleted", extra={"job_id": job_id})
            return True
        return False

    async def list_expired(self, ttl_hours: int) -> list[str]:
        expired = []
        import time
        now = time.time()
        for d in self.base_path.iterdir():
            if d.is_dir():
                try:
                    meta_path = d / "metadata.json"
                    if meta_path.exists():
                        data = json.loads(meta_path.read_text())
                        created = data.get("created_at", "")
                        if created:
                            created_ts = time.mktime(time.strptime(created[:19], "%Y-%m-%dT%H:%M:%S"))
                            if now - created_ts > ttl_hours * 3600:
                                expired.append(d.name)
                except Exception:
                    pass
        return expired
