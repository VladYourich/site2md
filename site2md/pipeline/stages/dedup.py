import hashlib

from site2md.core.logging import get_logger
from site2md.domain.models import PageResult

logger = get_logger(__name__)


def _simhash(text: str, n_grams: int = 5) -> int:
    shingles: dict[int, int] = {}
    for i in range(len(text) - n_grams + 1):
        shingle = text[i:i + n_grams]
        h = int(hashlib.md5(shingle.encode()).hexdigest()[:16], 16)
        shingles[h] = shingles.get(h, 0) + 1

    v = [0] * 64
    for shingle_hash, weight in shingles.items():
        for i in range(64):
            if (shingle_hash >> i) & 1:
                v[i] += weight
            else:
                v[i] -= weight

    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint


def _hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class DedupStage:
    SIMILARITY_THRESHOLD = 0.85
    MIN_BLOCK_LINES = 3
    BATCH_SIZE = 200

    async def process(self, pages: list[PageResult]) -> list[PageResult]:
        if not pages:
            return pages

        fingerprints: dict[str, set[int]] = {}

        for page in pages:
            if page.skipped or not page.extracted_html:
                continue

            from bs4 import BeautifulSoup
            try:
                soup = BeautifulSoup(page.extracted_html, "lxml")
            except Exception:
                continue

            blocks = self._extract_blocks(soup)
            page_fingerprints = []

            for block in blocks:
                text = block.get_text().strip()
                if text.count("\n") < self.MIN_BLOCK_LINES:
                    continue
                fp = _simhash(text)
                page_fingerprints.append((fp, block))

            is_duplicate = set()
            for fp, block in page_fingerprints:
                for _url, url_fps in fingerprints.items():
                    for existing_fp in url_fps:
                        distance = _hamming_distance(fp, existing_fp)
                        if distance / 64.0 <= (1 - self.SIMILARITY_THRESHOLD):
                            is_duplicate.add(block)
                            break

            for block in is_duplicate:
                block.decompose()

            page.extracted_html = str(soup)
            fingerprints[page.url] = {fp for fp, _ in page_fingerprints}

        return pages

    def _extract_blocks(self, soup) -> list:
        return soup.find_all(["div", "section", "article", "aside", "nav", "footer"])
