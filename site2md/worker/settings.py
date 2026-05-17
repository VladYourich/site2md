from site2md.config import settings
from site2md.core.logging import get_logger

logger = get_logger(__name__)

max_jobs = max(1, settings.concurrent_requests // 4)


class WorkerSettings:
    functions = ["site2md.worker.tasks.crawl_site"]
    from site2md.worker.tasks import crawl_site

    redis_settings = settings.redis_url
    max_jobs = 3
    job_timeout = settings.job_timeout
    max_tries = 2
    health_check_interval = 10
    keep_result_forever = False
    poll_delay = 0.5
    allow_abort_jobs = True
