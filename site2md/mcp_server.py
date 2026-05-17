import asyncio

from site2md.config import settings
from site2md.core.logging import get_logger, setup_logging
from site2md.core.redis import close_redis, init_redis

logger = get_logger(__name__)


async def main():
    setup_logging(settings.log_level)
    logger.info("Starting site2md MCP server")
    await init_redis()
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server

        server = Server("site2md")

        @server.tool()
        async def scrape_website(url: str, max_depth: int = 3, render_js: bool = False, chunk_delimiter: str = "\n><\n") -> dict:
            """Crawl a website and convert it to clean Markdown for RAG/LLM."""
            from site2md.core.security import validate_chunk_delimiter, validate_url_safety
            safe, error = validate_url_safety(url)
            if not safe:
                return {"error": str(error)}
            safe, error = validate_chunk_delimiter(chunk_delimiter)
            if not safe:
                return {"error": str(error)}
            if max_depth < 1 or max_depth > 5:
                return {"error": "max_depth must be between 1 and 5"}

            from site2md.core.redis import get_redis
            from site2md.services.crawl_service import CrawlService
            r = await get_redis()
            service = CrawlService(r)
            job = await service.create_crawl(
                url=url,
                max_depth=max_depth,
                render_js=render_js,
                chunk_delimiter=chunk_delimiter,
            )
            return {"job_id": job.job_id, "status": job.status.value}

        @server.tool()
        async def get_scrape_status(job_id: str) -> dict:
            """Get the status of a crawl job."""
            from site2md.core.redis import get_redis
            from site2md.services.crawl_service import CrawlService
            r = await get_redis()
            service = CrawlService(r)
            try:
                status = await service.get_status(job_id)
                return status.model_dump()
            except service.NotFoundError:
                return {"error": f"Job {job_id} not found"}

        @server.tool()
        async def get_scrape_result(job_id: str) -> dict:
            """Get the result (done.md) of a completed crawl job."""
            from site2md.core.redis import get_redis
            from site2md.services.crawl_service import CrawlService
            r = await get_redis()
            service = CrawlService(r)
            try:
                result = await service.get_result(job_id)
                return {"markdown": result}
            except service.NotFoundError:
                return {"error": f"Job {job_id} not found"}
            except service.JobNotCompleted:
                return {"error": f"Job {job_id} is not yet completed"}
            except service.ResultExpired:
                return {"error": f"Result for job {job_id} has expired"}

        logger.info("MCP server registered 3 tools: scrape_website, get_scrape_status, get_scrape_result")

        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    finally:
        await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
