
from pydantic import BaseModel, Field, model_validator

from site2md.core.security import validate_chunk_delimiter, validate_url_safety


class CrawlRequest(BaseModel):
    url: str = Field(description="Target website URL to crawl")
    max_depth: int = Field(default=3, ge=1, le=5, description="Maximum crawl depth")
    render_js: bool = Field(default=False, description="Force JS rendering for all pages")
    chunk_delimiter: str = Field(default="\n><\n", max_length=10, description="Chunk separator in output Markdown")

    @model_validator(mode="after")
    def validate_request(self) -> "CrawlRequest":
        safe, error = validate_url_safety(self.url)
        if not safe:
            raise ValueError(error)
        safe, error = validate_chunk_delimiter(self.chunk_delimiter)
        if not safe:
            raise ValueError(error)
        return self


class CrawlJobResponse(BaseModel):
    job_id: str
    status: str
    created_at: str
    url: str


class CrawlStatus(BaseModel):
    job_id: str
    status: str
    url: str
    pages_crawled: int
    pages_total: int | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    failed_urls: list[str] = Field(default_factory=list)
