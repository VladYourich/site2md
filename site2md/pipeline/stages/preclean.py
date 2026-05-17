from bs4 import BeautifulSoup, Tag

from site2md.core.logging import get_logger
from site2md.domain.models import PageResult

logger = get_logger(__name__)

REMOVE_TAGS = ["script", "style", "noscript", "iframe", "svg", "img", "nav", "footer", "header"]
NOISE_CLASSES = [
    "cookie", "gdpr", "consent", "cookie-banner", "cookie-notice",
    "ad-", "advertisement", "sponsored", "ad-container",
]
NOISE_IDS = ["cookie", "gdpr", "consent", "ad"]


class PreCleanStage:
    async def process(self, page: PageResult) -> PageResult:
        if page.skipped:
            return page
        try:
            soup = BeautifulSoup(page.raw_html, "lxml")
        except Exception:
            page.skipped = True
            page.skip_reason = "HTML parsing failed"
            return page

        for tag_name in REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        for tag in list(soup.find_all(True)):
            if not isinstance(tag, Tag):
                continue
            attrs = tag.attrs or {}
            style = (attrs.get("style") or "").lower().replace(" ", "")
            if "display:none" in style or "visibility:hidden" in style or "opacity:0" in style:
                tag.decompose()
                continue

        for tag in soup.find_all(attrs={"aria-hidden": "true"}):
            tag.decompose()

        for tag in list(soup.find_all(True)):
            if not isinstance(tag, Tag):
                continue
            attrs = tag.attrs or {}
            cls = attrs.get("class")
            if cls:
                cls_str = " ".join(cls).lower()
                if any(n in cls_str for n in NOISE_CLASSES):
                    tag.decompose()
                    continue
            tag_id = (attrs.get("id") or "").lower()
            if tag_id and any(n in tag_id for n in NOISE_IDS):
                tag.decompose()

        page.raw_html = str(soup)
        return page
