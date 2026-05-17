from bs4 import BeautifulSoup

from site2md.core.logging import get_logger
from site2md.domain.models import PageResult

logger = get_logger(__name__)


class PostProcessStage:
    async def process(self, page: PageResult) -> PageResult:
        if page.skipped:
            return page

        try:
            soup = BeautifulSoup(page.extracted_html, "lxml")
        except Exception:
            logger.warning("Failed to parse for PostProcess", extra={"url": page.url})
            return page

        for tag in soup.find_all(True):
            if tag.name in ("div", "span") and not tag.get_text(strip=True):
                tag.decompose()

        for tag in soup.find_all(["p", "div", "span", "li"]):
            if not tag.get_text(strip=True) and not tag.find("img"):
                tag.decompose()

        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        seen_levels = set()
        for h in headings:
            level = int(h.name[1])
            seen_levels.add(level)
        if seen_levels:
            min_level = min(seen_levels)
            if min_level > 1:
                for h in headings:
                    old = int(h.name[1])
                    new_level = old - (min_level - 1)
                    if new_level < 1:
                        new_level = 1
                    if new_level > 6:
                        new_level = 6
                    h.name = f"h{new_level}"

        for tag in soup.find_all("code"):
            if tag.parent and tag.parent.name != "pre":
                wrapper = soup.new_tag("pre")
                tag.wrap(wrapper)

        for tag in soup.find_all(attrs={"style": True}):
            del tag["style"]

        page.extracted_html = str(soup)
        return page
