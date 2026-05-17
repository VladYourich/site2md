"""
site2md Content Processing Pipeline
=====================================
Architecture: 6-stage pipeline with typed dataclasses between each stage.

Stage 1: PreClean   - Remove noise HTML elements (scripts, styles, hidden)
Stage 2: Extract   - trafilatura primary, readability-lxml fallback
Stage 3: PostProcess - BeautifulSoup structural fixes, hidden-element sweep
Stage 4: Dedup     - SimHash/SimHash-like cross-page boilerplate removal
Stage 5: Convert   - markdownify HTML -> Markdown with table handling
Stage 6: Assemble  - Combine pages into single done.md

Error model: per-page skip (log + continue) with optional fail-fast.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from functools import reduce
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag, Comment
from markdownify import markdownify as md, MarkdownConverter
from readability import Document as ReadabilityDocument
from readability.readability import Unparseable
from trafilatura import extract as trafilatura_extract
from trafilatura import bare_extraction
from trafilatura.settings import DEFAULT_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("site2md")


# ---------------------------------------------------------------------------
# 0. Shared types
# ---------------------------------------------------------------------------

class Stage(Enum):
    PRECLEAN = "preclean"
    EXTRACT = "extract"
    POSTPROCESS = "postprocess"
    DEDUP = "dedup"
    CONVERT = "convert"
    ASSEMBLE = "assemble"


@dataclass
class PageResult:
    url: str
    depth: int = 0
    title: str = ""
    raw_html: str = ""
    cleaned_html: str = ""
    extracted_html: str = ""
    postprocessed_html: str = ""
    markdown: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class PipelineStats:
    pages_total: int = 0
    pages_succeeded: int = 0
    pages_skipped: int = 0
    stages_failed: dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# A. Pipeline Architecture
# ---------------------------------------------------------------------------

class PipelineStage(ABC):
    """Base class for every processing stage."""

    name: str = ""

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"site2md.{self.name}")

    @abstractmethod
    def process(self, page: PageResult) -> PageResult:
        ...

    def __call__(self, page: PageResult) -> PageResult:
        if page.skipped:
            return page
        try:
            return self.process(page)
        except Exception as exc:
            page.skipped = True
            page.skip_reason = f"{self.name}: {exc}"
            page.errors.append(page.skip_reason)
            self.logger.warning("Skipping %s: %s", page.url, exc)
            return page


class Pipeline:
    """Compose stages and run them. Supports progress callback."""

    def __init__(self, stages: list[PipelineStage], *, on_progress: Optional[Callable] = None) -> None:
        self.stages = stages
        self.on_progress = on_progress

    def process_one(self, page: PageResult) -> PageResult:
        for stage in self.stages:
            page = stage(page)
            if self.on_progress:
                self.on_progress(stage.name, page)
        return page

    def process_many(
        self,
        pages: list[PageResult],
        *,
        max_workers: int = 4,
        fail_fast: bool = False,
    ) -> tuple[list[PageResult], PipelineStats]:
        stats = PipelineStats(pages_total=len(pages))
        t0 = time.monotonic()
        results: list[PageResult] = []

        if max_workers > 1:
            with ProcessPoolExecutor(max_workers=max_workers) as pool:
                for page in pool.map(self.process_one, pages):
                    results.append(page)
                    if fail_fast and page.skipped:
                        stats.elapsed_seconds = time.monotonic() - t0
                        return results, stats
        else:
            for page in pages:
                result = self.process_one(page)
                results.append(result)
                if fail_fast and result.skipped:
                    stats.elapsed_seconds = time.monotonic() - t0
                    return results, stats

        for r in results:
            if r.skipped:
                stats.pages_skipped += 1
                stage_name = r.skip_reason.split(":")[0].strip()
                stats.stages_failed[stage_name] = stats.stages_failed.get(stage_name, 0) + 1
            else:
                stats.pages_succeeded += 1

        stats.elapsed_seconds = time.monotonic() - t0
        return results, stats


# ---------------------------------------------------------------------------
# B. Stage 1: PreClean
# ---------------------------------------------------------------------------

HIDDEN_CSS_PATTERNS = [
    re.compile(r"display\s*:\s*none", re.I),
    re.compile(r"visibility\s*:\s*hidden", re.I),
    re.compile(r"opacity\s*:\s*0", re.I),
    re.compile(r"position\s*:\s*absolute\s*;\s*left\s*:\s*-?\d{4,}px", re.I),
    re.compile(r"height\s*:\s*0", re.I),
    re.compile(r"overflow\s*:\s*hidden\s*;\s*height\s*:\s*0", re.I),
]

AD_CLASS_PATTERNS = [
    re.compile(r"ad[-_]?(?:banner|container|slot|unit|wrapper)", re.I),
    re.compile(r"advertisement", re.I),
    re.compile(r"google[-_]ad", re.I),
    re.compile(r"sponsored", re.I),
    re.compile(r"promo[-_]?(?:box|sidebar|unit)", re.I),
]

AD_ID_PATTERNS = [
    re.compile(r"^ad[-_]?", re.I),
    re.compile(r"google_ad", re.I),
    re.compile(r"ad_?", re.I),
]

MODAL_PATTERNS = [
    re.compile(r"modal|popup|overlay|lightbox|cookie[-_]?notice|gdpr|consent[-_]?banner", re.I),
]

REMOVE_TAGS = {"script", "style", "noscript", "iframe", "svg", "img"}
REMOVE_ROLES = {"navigation", "banner", "contentinfo", "complementary"}


class PreCleanStage(PipelineStage):
    name = "preclean"

    def process(self, page: PageResult) -> PageResult:
        soup = BeautifulSoup(page.raw_html, "lxml")

        self._remove_noise_tags(soup)
        self._remove_hidden_elements(soup)
        self._remove_ads(soup)
        self._remove_cookie_modals(soup)
        self._remove_aria_hidden(soup)
        self._remove_comments(soup)

        page.cleaned_html = str(soup)
        return page

    def _remove_noise_tags(self, soup: BeautifulSoup) -> None:
        for tag in soup.find_all(REMOVE_TAGS):
            tag.decompose()

    def _remove_hidden_elements(self, soup: BeautifulSoup) -> None:
        for el in soup.find_all(True):
            style = el.get("style", "")
            if not isinstance(style, str):
                continue
            for pattern in HIDDEN_CSS_PATTERNS:
                if pattern.search(style):
                    el.decompose()
                    break

    def _remove_ads(self, soup: BeautifulSoup) -> None:
        for el in soup.find_all(True):
            cls = " ".join(el.get("class", []))
            el_id = el.get("id", "")
            if any(p.search(cls) for p in AD_CLASS_PATTERNS):
                el.decompose()
                continue
            if any(p.search(el_id) for p in AD_ID_PATTERNS):
                el.decompose()

    def _remove_cookie_modals(self, soup: BeautifulSoup) -> None:
        for el in soup.find_all(True):
            cls = " ".join(el.get("class", []))
            el_id = el.get("id", "")
            combined = cls + " " + el_id
            if any(p.search(combined) for p in MODAL_PATTERNS):
                el.decompose()
                continue
            role = el.get("role", "")
            if role in REMOVE_ROLES:
                el.decompose()

    def _remove_aria_hidden(self, soup: BeautifulSoup) -> None:
        for el in soup.find_all(attrs={"aria-hidden": "true"}):
            el.decompose()

    def _remove_comments(self, soup: BeautifulSoup) -> None:
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()


# ---------------------------------------------------------------------------
# B. Stage 2: Extract  (trafilatura → readability-lxml fallback)
# ---------------------------------------------------------------------------

class ExtractStage(PipelineStage):
    name = "extract"

    MIN_CONTENT_LENGTH = 50

    def process(self, page: PageResult) -> PageResult:
        result = self._trafilatura_extract(page)
        if result is None or len(result.strip()) < self.MIN_CONTENT_LENGTH:
            self.logger.info("trafilatura failed or too short for %s, trying readability", page.url)
            result = self._readability_extract(page)
        if result is None:
            page.skipped = True
            page.skip_reason = "extract: both trafilatura and readability returned empty"
            page.errors.append(page.skip_reason)
            return page
        page.extracted_html = result
        return page

    def _trafilatura_extract(self, page: PageResult) -> Optional[str]:
        try:
            return trafilatura_extract(
                page.cleaned_html,
                url=page.url,
                output_format="html",
                favor_precision=True,
                include_comments=False,
                include_tables=True,
                include_formatting=True,
                include_links=True,
                deduplicate=True,
                with_metadata=False,
            )
        except Exception as exc:
            self.logger.debug("trafilatura error for %s: %s", page.url, exc)
            return None

    def _readability_extract(self, page: PageResult) -> Optional[str]:
        try:
            doc = ReadabilityDocument(page.cleaned_html, url=page.url)
            return doc.summary(html_partial=True)
        except (Unparseable, Exception) as exc:
            self.logger.debug("readability error for %s: %s", page.url, exc)
            return None


# ---------------------------------------------------------------------------
# B. Stage 3: PostProcess  (BeautifulSoup structural fixes)
# ---------------------------------------------------------------------------

class PostProcessStage(PipelineStage):
    name = "postprocess"

    def process(self, page: PageResult) -> PageResult:
        soup = BeautifulSoup(page.extracted_html, "lxml")
        self._flatten_nested_divs(soup)
        self._remove_empty_tags(soup)
        self._normalize_headings(soup)
        self._ensure_list_structure(soup)
        self._wrap_bare_code(soup)
        self._remove_remaining_hidden(soup)
        page.postprocessed_html = str(soup)
        return page

    def _flatten_nested_divs(self, soup: BeautifulSoup) -> None:
        changed = True
        while changed:
            changed = False
            for div in soup.find_all("div"):
                children = [c for c in div.children if isinstance(c, Tag)]
                if len(children) == 1 and children[0].name == "div":
                    div.unwrap()
                    changed = True

    def _remove_empty_tags(self, soup: BeautifulSoup) -> None:
        for el in soup.find_all(True):
            if el.name not in {"br", "hr", "img", "iframe"} and not el.get_text(strip=True):
                el.decompose()

    def _normalize_headings(self, soup: BeautifulSoup) -> None:
        for tag_name in [f"h{i}" for i in range(1, 7)]:
            for heading in soup.find_all(tag_name):
                heading.string = heading.get_text(strip=True)

    def _ensure_list_structure(self, soup: BeautifulSoup) -> None:
        for li in soup.find_all("li"):
            if li.parent.name not in {"ul", "ol"}:
                ul = soup.new_tag("ul")
                li.wrap(ul)

    def _wrap_bare_code(self, soup: BeautifulSoup) -> None:
        for pre in soup.find_all("pre"):
            if not pre.find("code"):
                code = soup.new_tag("code")
                code.string = pre.get_text()
                pre.clear()
                pre.append(code)

    def _remove_remaining_hidden(self, soup: BeautifulSoup) -> None:
        for el in soup.find_all(attrs={"aria-hidden": "true"}):
            el.decompose()
        for el in soup.find_all(True):
            style = el.get("style", "")
            if isinstance(style, str) and "display:none" in style.replace(" ", "").lower():
                el.decompose()


# ---------------------------------------------------------------------------
# B. Stage 4: Dedup  (cross-page boilerplate removal via SimHash)
# ---------------------------------------------------------------------------


def _simhash(tokens: list[str], hash_bits: int = 128) -> int:
    """Compute a SimHash fingerprint from a list of tokens."""
    v = [0] * hash_bits
    for token in tokens:
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        for i in range(hash_bits):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1
    fingerprint = 0
    for i in range(hash_bits):
        if v[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def _hamming_distance(a: int, b: int, hash_bits: int = 128) -> int:
    return bin(a ^ b).count("1")


def _shingle_text(text: str, k: int = 5) -> list[str]:
    """Create character n-gram shingles."""
    words = text.lower().split()
    if len(words) < k:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + k]) for i in range(len(words) - k + 1)]


@dataclass
class BlockFingerprint:
    block_hash: int
    text: str
    line_count: int


class DedupStage(PipelineStage):
    name = "dedup"

    def __init__(self, similarity_threshold: float = 0.85, min_block_lines: int = 3) -> None:
        super().__init__()
        self.similarity_threshold = similarity_threshold
        self.min_block_lines = min_block_lines
        self._global_fingerprints: list[BlockFingerprint] = []

    def process(self, page: PageResult) -> PageResult:
        blocks = self._split_into_blocks(page.postprocessed_html)
        filtered_blocks: list[str] = []
        for block_html, block_text in blocks:
            lines = [l for l in block_text.strip().splitlines() if l.strip()]
            if len(lines) < self.min_block_lines:
                filtered_blocks.append(block_html)
                continue
            fp = _simhash(_shingle_text(block_text))
            if self._is_near_duplicate(fp, len(lines)):
                self.logger.debug("Dedup: removed block from %s (%d lines)", page.url, len(lines))
                continue
            self._global_fingerprints.append(BlockFingerprint(fp, block_text[:80], len(lines)))
            filtered_blocks.append(block_html)

        page.postprocessed_html = "\n".join(filtered_blocks)
        return page

    def _split_into_blocks(self, html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        blocks = []
        for el in soup.find_all(True):
            if el.name in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "pre", "blockquote", "section"}:
                text = el.get_text(strip=True)
                if text:
                    blocks.append((str(el), text))
        return blocks

    def _is_near_duplicate(self, fingerprint: int, line_count: int) -> bool:
        for existing in self._global_fingerprints:
            if abs(existing.line_count - line_count) > max(2, line_count * 0.3):
                continue
            dist = _hamming_distance(fingerprint, existing.block_hash)
            similarity = 1.0 - dist / 128.0
            if similarity >= self.similarity_threshold:
                return True
        return False


# ---------------------------------------------------------------------------
# B. Stage 5: Convert  (HTML → Markdown via markdownify)
# ---------------------------------------------------------------------------


class Site2mdConverter(MarkdownConverter):
    """Extended markdownify converter with table header inference and code handling."""

    def convert_table(self, el, text, parent_tags):
        has_thead = el.find("thead") is not None
        has_th_first_row = bool(el.find("tr").find("th")) if el.find("tr") else False
        return super().convert_table(el, text, parent_tags)

    def convert_pre(self, el, text, parent_tags):
        code_el = el.find("code")
        if code_el:
            lang = ""
            for cls in code_el.get("class", []):
                if cls.startswith(("language-", "lang-")):
                    lang = cls.split("-", 1)[1]
                    break
            inner = code_el.get_text()
            return f"\n```{lang}\n{inner}\n```\n"
        return f"\n```\n{text}\n```\n"


def _handle_complex_table(table_html: str) -> str:
    soup = BeautifulSoup(table_html, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return table_html
    for table in tables:
        has_rowspan = table.find(attrs={"rowspan": True}) is not None
        has_colspan = table.find(attrs={"colspan": True}) is not None
        if has_rowspan or has_colspan:
            md_table = md(str(table), heading_style="#", table_infer_header=True)
            if md_table.count("|") < 3:
                return f"\n<!-- complex table, raw HTML -->\n{table}\n"
    return md(table_html, heading_style="#", table_infer_header=True)


class ConvertStage(PipelineStage):
    name = "convert"

    def process(self, page: PageResult) -> PageResult:
        html = page.postprocessed_html
        if not html:
            page.skipped = True
            page.skip_reason = "convert: empty HTML"
            page.errors.append(page.skip_reason)
            return page

        page.markdown = md(
            html,
            heading_style="#",
            bullets="-",
            strip=["img", "figure"],
            table_infer_header=True,
            convert=["p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
                     "pre", "code", "blockquote", "table", "a", "strong", "em",
                     "br", "hr", "dl", "dt", "dd"],
        )
        page.markdown = self._clean_markdown(page.markdown)

        title = page.metadata.get("title") or page.title
        if title:
            page.metadata["title"] = title

        return page

    def _clean_markdown(self, text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"^\s+", "", text, flags=re.MULTILINE)
        text = text.strip()
        return text


# ---------------------------------------------------------------------------
# B. Stage 6: Assemble
# ---------------------------------------------------------------------------

@dataclass
class AssemblyConfig:
    toc: bool = True
    page_separator: str = "\n\n---\n\n"
    include_metadata: bool = True
    include_source_url: bool = True
    heading_base_level: int = 2
    sort_by: str = "depth_then_path"


class AssembleStage(PipelineStage):
    name = "assemble"

    def __init__(self, config: AssemblyConfig | None = None) -> None:
        super().__init__()
        self.config = config or AssemblyConfig()

    def process(self, page: PageResult) -> PageResult:
        return page

    def assemble(self, pages: list[PageResult], output_path: Path | None = None) -> str:
        sorted_pages = self._sort_pages(pages)
        sections: list[str] = []
        toc_entries: list[str] = []

        for page in sorted_pages:
            if page.skipped:
                continue
            section_md, heading = self._build_section(page)
            if heading:
                toc_entries.append(f"- [{heading}](#{self._slugify(heading)})")
            sections.append(section_md)

        doc = ""
        if self.config.toc and toc_entries:
            doc += "# Table of Contents\n\n"
            doc += "\n".join(toc_entries) + "\n\n"

        doc += self.config.page_separator.join(sections)

        if output_path:
            output_path.write_text(doc, encoding="utf-8")

        return doc

    def _sort_pages(self, pages: list[PageResult]) -> list[PageResult]:
        if self.config.sort_by == "depth_then_path":
            return sorted(pages, key=lambda p: (p.depth, urlparse(p.url).path))
        return sorted(pages, key=lambda p: urlparse(p.url).path)

    def _build_section(self, page: PageResult) -> tuple[str, str]:
        heading = page.metadata.get("title") or page.title or self._path_to_title(page.url)
        level = self.config.heading_base_level + page.depth
        level = min(level, 6)
        prefix = "#" * level

        parts: list[str] = []
        if self.config.include_metadata:
            meta_lines = [f"**Source:** {page.url}"]
            if page.metadata.get("date"):
                meta_lines.append(f"**Crawled:** {page.metadata['date']}")
            parts.append("\n".join(meta_lines))

        parts.append(f"{prefix} {heading}\n\n{page.markdown}")

        return "\n\n".join(parts), heading

    @staticmethod
    def _path_to_title(url: str) -> str:
        path = urlparse(url).path.strip("/")
        title = path.split("/")[-1] if path else urlparse(url).netloc
        return title.replace("-", " ").replace("_", " ").title()

    @staticmethod
    def _slugify(text: str) -> str:
        return re.sub(r"[^\w-]", "", re.sub(r"\s+", "-", text.lower()))


# ---------------------------------------------------------------------------
# C. Putting it all together
# ---------------------------------------------------------------------------

def build_pipeline(
    dedup_threshold: float = 0.85,
    assembly_config: AssemblyConfig | None = None,
    on_progress: Callable | None = None,
) -> Pipeline:
    stages = [
        PreCleanStage(),
        ExtractStage(),
        PostProcessStage(),
        DedupStage(similarity_threshold=dedup_threshold),
        ConvertStage(),
        AssembleStage(config=assembly_config),
    ]
    return Pipeline(stages, on_progress=on_progress)


def process_site(
    pages: list[PageResult],
    output_path: Path = Path("done.md"),
    max_workers: int = 4,
    dedup_threshold: float = 0.85,
    assembly_config: AssemblyConfig | None = None,
) -> tuple[str, PipelineStats]:
    pipeline = build_pipeline(
        dedup_threshold=dedup_threshold,
        assembly_config=assembly_config,
        on_progress=lambda stage, page: logger.info("[%s] %s → %s", stage, page.url, "skip" if page.skipped else "ok"),
    )

    results, stats = pipeline.process_many(pages, max_workers=max_workers)

    assemble_stage = next(s for s in pipeline.stages if isinstance(s, AssembleStage))
    final_md = assemble_stage.assemble(results, output_path=output_path)

    logger.info("Pipeline complete: %d/%d pages succeeded, %d skipped, %.1fs elapsed",
                stats.pages_succeeded, stats.pages_total, stats.pages_skipped, stats.elapsed_seconds)

    return final_md, stats


# ---------------------------------------------------------------------------
# D. Usage example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample_pages = [
        PageResult(
            url="https://example.com/docs/intro",
            depth=0,
            title="Introduction",
            raw_html="""
            <html><head><title>Intro</title></head>
            <body>
              <script>var x=1;</script>
              <style>.hidden{display:none}</style>
              <nav><a href="/">Home</a></nav>
              <div class="ad-banner">Buy stuff!</div>
              <div aria-hidden="true">Hidden cookie notice</div>
              <article>
                <h1>Welcome</h1>
                <p>This is the <strong>introduction</strong>.</p>
                <table>
                  <thead><tr><th>Feature</th><th>Status</th></tr></thead>
                  <tbody><tr><td>Crawl</td><td>Done</td></tr></tbody>
                </table>
                <pre><code class="language-python">print("hello")</code></pre>
              </article>
              <footer>Copyright 2025</footer>
            </body></html>
            """,
        ),
        PageResult(
            url="https://example.com/docs/advanced",
            depth=1,
            title="Advanced Usage",
            raw_html="""
            <html><head><title>Advanced</title></head>
            <body>
              <script>console.log("ad")</script>
              <div class="ad-banner">Buy stuff!</div>
              <article>
                <h2>Advanced</h2>
                <p>More content here with <a href="/link">a link</a>.</p>
                <ul>
                  <li>Item 1</li>
                  <li>Item 2</li>
                </ul>
              </article>
            </body></html>
            """,
        ),
    ]

    md_output, stats = process_site(sample_pages, output_path=Path("done.md"))
    print(md_output)
    print(f"\n--- Stats: {stats}")