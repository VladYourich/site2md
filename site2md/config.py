from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 20
    storage_path: str = "/data/results"
    max_pages: int = 200
    max_depth: int = 5
    max_response_size: int = 10 * 1024 * 1024
    job_timeout: int = 600
    download_delay: float = 1.0
    concurrent_requests: int = 16
    playwright_max_contexts: int = 4
    playwright_page_timeout: int = 10000
    result_ttl_hours: int = 24
    log_level: str = "INFO"
    api_workers: int = 2

    @property
    def storage_path_resolved(self) -> Path:
        return Path(self.storage_path)


settings = Settings()
