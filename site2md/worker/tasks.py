import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from site2md.config import settings
from site2md.core.logging import get_logger
from site2md.core.metrics import (
    crawl_duration_seconds,
    crawl_requests_total,
    pages_crawled_total,
)
from site2md.core.redis import get_redis
from site2md.core.security import validate_url_safety
from site2md.domain.models import CrawlJobStatus, PageResult
from site2md.pipeline.core import Pipeline
from site2md.services.crawl_service import CrawlService
from site2md.services.storage_service import StorageService

logger = get_logger(__name__)


async def crawl_site(
    ctx,
    job_id: str,
    url: str,
    max_depth: int = 3,
    render_js: bool = False,
    chunk_delimiter: str = "\n><\n",
) -> dict:
    start_time = time.time()
    logger.info("Starting crawl", extra={"job_id": job_id, "url": url})

    r = await get_redis()
    service = CrawlService(r)
    storage = StorageService()

    try:
        key = service._metadata_key(job_id)
        await r.hset(key, mapping={
            "status": CrawlJobStatus.RUNNING.value,
            "started_at": datetime.now(UTC).isoformat(),
        })

        parsed_base = urlparse(url)
        base_domain = parsed_base.netloc

        import httpx
        from bs4 import BeautifulSoup as BS

        browser = None
        pw = None
        if render_js:
            try:
                from playwright.async_api import async_playwright
                pw = await async_playwright().start()
                browser = await pw.chromium.launch(headless=True)
            except Exception as e:
                logger.warning(
                    "Playwright launch failed, continuing without JS rendering",
                    extra={"job_id": job_id, "error": str(e)},
                )

        async def check_cancel() -> bool:
            return await r.exists(f"crawl:{job_id}:cancel") > 0

        results: list[PageResult] = []
        visited: set[str] = set()
        pages_queue: list[tuple[str, int]] = [(url, 0)]
        page_count = 0

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": "site2md/0.1.0 (+https://github.com/site2md)"},
        ) as client:

            while pages_queue and page_count < settings.max_pages:
                if await check_cancel():
                    logger.info("Crawl cancelled during execution", extra={"job_id": job_id})
                    break

                current_url, depth = pages_queue.pop(0)
                if current_url in visited:
                    continue
                if depth > max_depth:
                    continue

                safe, _ = validate_url_safety(current_url)
                if not safe:
                    visited.add(current_url)
                    continue

                visited.add(current_url)

                try:
                    html_content = ""
                    render_mode = "static"

                    if render_js and browser:
                        try:
                            ctx = await browser.new_context()
                            page = await ctx.new_page()
                            await page.goto(current_url, wait_until="domcontentloaded", timeout=settings.playwright_page_timeout)
                            html_content = await page.content()
                            render_mode = "playwright"
                            await ctx.close()
                        except Exception as e:
                            logger.warning("Playwright render failed", extra={"url": current_url, "error": str(e)})

                    if not html_content:
                        resp = await client.get(current_url)
                        html_content = resp.text
                        render_mode = "static"

                    page_count += 1
                    with contextlib.suppress(Exception):
                        await service.update_progress(job_id, page_count)

                    soup = BS(html_content, "html.parser")
                    title = soup.title.string if soup.title else ""

                    result = PageResult(
                        url=current_url,
                        title=title,
                        depth=depth,
                        raw_html=html_content,
                        render_mode=render_mode,
                    )
                    results.append(result)

                    if depth < max_depth:
                        for link in soup.find_all("a", href=True):
                            href = link.get("href", "")
                            if not href:
                                continue
                            full_url = urljoin(current_url, href)
                            pu = urlparse(full_url)
                            if pu.scheme not in ("http", "https"):
                                continue
                            if pu.netloc == base_domain or pu.netloc.endswith("." + base_domain):
                                clean_url = pu._replace(fragment="").geturl()
                                if clean_url not in visited:
                                    pages_queue.append((clean_url, depth + 1))
                                    if len(pages_queue) > settings.max_pages * 3:
                                        pages_queue = pages_queue[: settings.max_pages * 3]

                except Exception as e:
                    logger.warning("Page fetch failed", extra={"url": current_url, "error": str(e)})
                    results.append(PageResult(
                        url=current_url,
                        depth=depth,
                        skipped=True,
                        skip_reason=str(e),
                    ))

        if pw and browser:
            try:
                await browser.close()
                await pw.stop()
            except Exception:
                pass

        if not results:
            await r.hset(key, mapping={
                "status": CrawlJobStatus.FAILED.value,
                "completed_at": datetime.now(UTC).isoformat(),
                "error": "No pages were crawled",
            })
            crawl_requests_total.labels(status="failed").inc()
            return {"status": "failed", "pages_crawled": 0}

        pipeline = Pipeline()
        markdown, processed_pages, stats = await pipeline.run(results, chunk_delimiter)

        failed_urls = [p.url for p in processed_pages if p.skipped]

        error_count = stats.get("error", 0)
        total_processed = stats.get("success", 0) + error_count
        status = CrawlJobStatus.COMPLETED.value if error_count == 0 else CrawlJobStatus.COMPLETED_WITH_ERRORS.value

        result_path = await storage.store_result(job_id, markdown, {
            "created_at": datetime.now(UTC).isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "url": url,
            "pages_crawled": total_processed,
            "status": status,
        })

        await r.hset(key, mapping={
            "status": status,
            "pages_crawled": str(total_processed),
            "result_path": result_path,
            "completed_at": datetime.now(UTC).isoformat(),
            "failed_urls": json.dumps(failed_urls),
            "pages_total": str(len(results)),
        })

        duration = time.time() - start_time
        crawl_duration_seconds.labels(status="completed").observe(duration)
        crawl_requests_total.labels(status="completed").inc()
        pages_crawled_total.labels(render_mode="mixed").inc(stats.get("success", 0))

        logger.info("Crawl completed", extra={"job_id": job_id, "pages": stats.get("success", 0), "duration": duration})
        return {"status": "completed", "pages_crawled": stats.get("success", 0)}

    except asyncio.CancelledError:
        await r.hset(key, mapping={
            "status": CrawlJobStatus.CANCELLED.value,
            "completed_at": datetime.now(UTC).isoformat(),
        })
        return {"status": "cancelled"}

    except Exception as e:
        logger.error("Crawl failed", extra={"job_id": job_id, "error": str(e)})
        with contextlib.suppress(Exception):
            await r.hset(key, mapping={
                "status": CrawlJobStatus.FAILED.value,
                "completed_at": datetime.now(UTC).isoformat(),
                "error": str(e),
            })
        crawl_requests_total.labels(status="failed").inc()
        duration = time.time() - start_time
        crawl_duration_seconds.labels(status="failed").observe(duration)
        raise
