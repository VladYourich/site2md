import enum
from dataclasses import dataclass, field
from datetime import datetime


class CrawlJobStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CrawlJob:
    job_id: str
    url: str
    status: CrawlJobStatus = CrawlJobStatus.PENDING
    max_depth: int = 3
    render_js: bool = False
    chunk_delimiter: str = "\n><\n"
    pages_crawled: int = 0
    pages_total: int | None = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result_path: str | None = None
    failed_urls: list[str] = field(default_factory=list)


@dataclass
class PageResult:
    url: str
    title: str = ""
    depth: int = 0
    raw_html: str = ""
    extracted_html: str = ""
    markdown: str = ""
    metadata: dict = field(default_factory=dict)
    skipped: bool = False
    skip_reason: str = ""
    render_mode: str = "static"
    crawl_date: datetime = field(default_factory=datetime.now)


@dataclass
class PipelineStats:
    success_count: int = 0
    skip_count: int = 0
    error_count: int = 0
    duration_per_stage: dict[str, float] = field(default_factory=dict)
