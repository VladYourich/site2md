import re
from datetime import datetime

from site2md.core.logging import get_logger
from site2md.domain.models import PageResult

logger = get_logger(__name__)


class AssembleStage:
    async def process(self, pages: list[PageResult], chunk_delimiter: str = "\n><\n") -> str:
        active_pages = [p for p in pages if not p.skipped and p.markdown.strip()]
        active_pages.sort(key=lambda p: (p.depth, p.url))

        lines: list[str] = []
        lines.append(f"# Site Content: {pages[0].url if pages else 'Unknown'}")
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append("")

        if active_pages:
            lines.append("## Table of Contents")
            lines.append("")
            for page in active_pages:
                indent = "  " * page.depth
                title = page.title or page.url.rsplit("/", 1)[-1] or page.url
                anchor = title.lower().replace(" ", "-").replace(".", "")
                lines.append(f"{indent}- [{title}](#{anchor})")
            lines.append("")

        for page in active_pages:
            heading_level = min(page.depth + 2, 6)
            heading_prefix = "#" * heading_level
            safe_title = self._escape_markers(page.title or page.url, chunk_delimiter)

            lines.append(f"{heading_prefix} {safe_title}")
            lines.append(f"<!-- source: {page.url} | crawled: {page.metadata.get('crawl_date', datetime.now().isoformat())} -->")
            lines.append("")

            blocks = self._split_blocks(page.markdown)
            for i, block in enumerate(blocks):
                cleaned = self._escape_markers(block.strip(), chunk_delimiter)
                if cleaned:
                    lines.append(cleaned)
                    if i < len(blocks) - 1:
                        lines.append(chunk_delimiter)

            lines.append("")
            lines.append("---")
            lines.append("")

        total_skipped = len([p for p in pages if p.skipped])
        if total_skipped > 0:
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append("## Processing Notes")
            lines.append(f"Skipped {total_skipped} pages:")
            for p in pages:
                if p.skipped:
                    lines.append(f"- [{p.url}]({p.url}): {p.skip_reason}")

        return "\n".join(lines)

    def _split_blocks(self, markdown: str) -> list[str]:
        blocks = re.split(r"\n(?:#{1,6}\s|(?:\n-{3,}\n))", markdown)
        if not blocks or blocks == [markdown]:
            return [markdown]
        result = []
        prev_end = 0
        for pattern in re.finditer(r"\n(#{1,6}\s|(?:\n-{3,}\n))", markdown):
            result.append(markdown[prev_end:pattern.start()].strip())
            prev_end = pattern.end()
        result.append(markdown[prev_end:].strip())
        return [b for b in result if b]

    def _escape_markers(self, text: str, delimiter: str) -> str:
        if not delimiter:
            return text
        escaped = delimiter.replace("\\", "\\\\").replace(">", "\\>").replace("<", "\\<")
        return text.replace(delimiter, escaped)
