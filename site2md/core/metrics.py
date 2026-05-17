from prometheus_client import Counter, Gauge, Histogram

crawl_requests_total = Counter(
    "site2md_crawl_requests_total",
    "Total crawl requests",
    ["status"],
)

pages_crawled_total = Counter(
    "site2md_pages_crawled_total",
    "Total pages crawled",
    ["render_mode"],
)

pipeline_stages_total = Counter(
    "site2md_pipeline_stages_total",
    "Pipeline stage executions",
    ["stage", "result"],
)

crawl_duration_seconds = Histogram(
    "site2md_crawl_duration_seconds",
    "Crawl job duration",
    ["status"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1200],
)

queue_depth = Gauge(
    "site2md_queue_depth",
    "Current pending jobs in queue",
)
