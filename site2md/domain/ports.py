from abc import ABC, abstractmethod


class StoragePort(ABC):
    @abstractmethod
    async def store_result(self, job_id: str, markdown_content: str, metadata: dict) -> str:
        ...

    @abstractmethod
    async def read_result(self, job_id: str) -> str | None:
        ...

    @abstractmethod
    async def delete_result(self, job_id: str) -> bool:
        ...

    @abstractmethod
    async def list_expired(self, ttl_hours: int) -> list[str]:
        ...
