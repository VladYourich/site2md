from site2md.core.logging import get_logger
from site2md.domain.models import PageResult

logger = get_logger(__name__)


class ExtractStage:
    async def process(self, page: PageResult) -> PageResult:
        if page.skipped:
            return page

        try:
            import trafilatura
            result = trafilatura.extract(
                page.raw_html,
                favor_precision=True,
                include_tables=True,
                output_format="html",
                url=page.url,
            )
        except Exception as e:
            logger.warning("trafilatura extraction failed", extra={"url": page.url, "error": str(e)})
            result = ""

        if result and len(result.strip()) >= 50:
            page.extracted_html = result
            page.render_mode = "trafilatura"
            return page

        try:
            from readability import Document
            doc = Document(page.raw_html)
            summary = doc.summary(html_partial=True)
        except Exception as e:
            logger.warning("readability fallback failed", extra={"url": page.url, "error": str(e)})
            summary = ""

        if summary and len(summary.strip()) >= 50:
            page.extracted_html = summary
            page.render_mode = "readability"
            return page

        page.skipped = True
        page.skip_reason = "No content extracted"
        return page
