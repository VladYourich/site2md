from markdownify import MarkdownConverter

from site2md.core.logging import get_logger
from site2md.domain.models import PageResult

logger = get_logger(__name__)


class Site2mdConverter(MarkdownConverter):
    def convert_code(self, el, text, convert_as_inline):
        lang = el.get("class", [""])[0] if el.get("class") else ""
        lang = lang[len("language-"):] if lang.startswith("language-") else ""
        if lang:
            return f"\n\n```{lang}\n{text}\n```\n\n"
        return f"\n\n```\n{text}\n```\n\n"

    def convert_pre(self, el, text, convert_as_inline):
        if el.find("code"):
            return text
        return f"\n\n```\n{text}\n```\n\n"


def _md_convert(html: str, **options) -> str:
    return Site2mdConverter(heading_style="ATX", **options).convert(html)


class ConvertStage:
    async def process(self, pages: list[PageResult]) -> list[PageResult]:
        for page in pages:
            if page.skipped or not page.extracted_html:
                continue

            try:
                page.markdown = _md_convert(page.extracted_html)
            except Exception as e:
                logger.warning("Markdown conversion failed", extra={"url": page.url, "error": str(e)})
                page.skipped = True
                page.skip_reason = f"Convert failed: {e}"

        return pages
