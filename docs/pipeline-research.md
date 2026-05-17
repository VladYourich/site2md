# site2md Pipeline Architecture — Best Practices Research (2025-2026)

## A. Pipeline Architecture

### Pipeline Pattern vs Chain of Responsibility

| Pattern | Pros | Cons |
|---------|------|------|
| **Pipeline** (chosen) | Each stage is independent, testable, replaceable. Stages share typed dataclass (`PageResult`). Easy to add/remove/reorder stages. | All stages see the same data shape — less fine-grained isolation |
| Chain of Responsibility | Each handler decides whether to pass along. Good for conditional routing. | Harder to reason about data flow. Overkill for a linear transform pipeline |

**Decision: Pipeline** — The site2md transform is strictly linear (PreClean → Extract → PostProcess → Dedup → Convert → Assemble). A pipeline where each stage receives `PageResult` and returns `PageResult` is the simplest correct architecture.

### Stage Composition

```
RawHTML → PreClean → Extract → PostProcess → Dedup → Convert → Assemble → done.md
             │          │          │            │         │
          PageResult  PageResult  PageResult  PageResult PageResult
```

Each stage:
1. Receives a `PageResult` 
2. Writes to the next field in the dataclass (`cleaned_html`, `extracted_html`, `postprocessed_html`, `markdown`)
3. On failure: marks `skipped=True`, sets `skip_reason`, appends to `errors`
4. Returns the modified `PageResult` — never raises to the pipeline runner

### Error Handling Strategy: Skip Page vs Fail Crawl

**Default: skip page, log, continue.** Rationale: A site with 500 pages where 3 fail should still produce a useful `done.md`. The alternative (fail-fast) is available via `fail_fast=True` on `Pipeline.process_many()`.

| Error | Behavior |
|-------|----------|
| PreClean fails | Skip page (likely malformed HTML) |
| Extract returns empty | Skip page (no content found) |
| PostProcess fails | Skip page (structural fix bombed) |
| Dedup removes all blocks | Keep page with empty markdown (header preserved) |
| Convert fails | Skip page |
| Assemble fails | Never per-page (assembly is batch) |

### Progress Reporting

Each stage can receive a callback via `Pipeline(on_progress=fn)`. The signature is `fn(stage_name: str, page: PageResult)`. This enables:

- CLI progress bars (tqdm)
- WebSocket status push
- Logging

---

## B. Content Extraction Pipeline — Stage Details

### Stage 1: PreClean

| | Detail |
|---|--------|
| **Input** | `page.raw_html` (full HTML from crawler) |
| **Output** | `page.cleaned_html` (HTML stripped of noise) |
| **Removes** | `<script>`, `<style>`, `<noscript>`, `<iframe>`, hidden elements, ads, cookie notices, `aria-hidden="true"`, HTML comments |
| **Error handling** | BeautifulSoup's `lxml` parser is extremely tolerant. If parsing fails entirely, the page is skipped. |

**Hidden element detection strategies** (see Section D for full details):

- Inline `style` regex matching for `display:none`, `visibility:hidden`, `opacity:0`, offscreen positioning
- `aria-hidden="true"` attribute removal
- Ad container detection via class/id regex patterns
- Modal/popup/cookie-notice detection via class/id regex patterns
- ARIA landmark roles: `role="navigation"`, `role="banner"`, `role="contentinfo"`, `role="complementary"`

**Performance**: BeautifulSoup with lxml parser handles 100KB HTML in ~5ms. CPU-bound, parallelizable later.

### Stage 2: Extract (trafilatura + readability-lxml fallback)

| | Detail |
|---|--------|
| **Input** | `page.cleaned_html` |
| **Output** | `page.extracted_html` (article content only, as HTML) |
| **Primary** | trafilatura with `favor_precision=True`, `include_tables=True`, `deduplicate=True` |
| **Fallback** | readability-lxml `Document.summary(html_partial=True)` |

**Why trafilatura as primary?**

- trafilatura (2024-2025) is the state-of-the-art for content extraction, outperforming readability, newspaper3k, and goose3 in evaluations
- Built-in deduplication of repeated content blocks
- `favor_precision=True` gives cleaner output (fewer false positives at the cost of sometimes missing marginal content)
- Native `output_format="html"` preserves structural elements needed for later stages
- Falls back to readability-lxml when trafilatura returns empty or <50 chars

**Minimum content threshold**: 50 characters. Pages below this are either extraction failures or truly empty.

### Stage 3: PostProcess

| | Detail |
|---|--------|
| **Input** | `page.extracted_html` |
| **Output** | `page.postprocessed_html` |
| **Fixes** | Nested div flattening, empty tag removal, heading normalization, list structure repair, bare code wrapping, second-pass hidden element removal |

**Why a second pass for hidden elements?** Trafilatura/readability may re-introduce hidden elements from their internal template processing. The post-process sweep catches stragglers.

### Stage 4: Dedup (Cross-Page Boilerplate Removal)

| | Detail |
|---|--------|
| **Input** | `page.postprocessed_html` (per page, processed sequentially after all pages complete earlier stages) |
| **Output** | `page.postprocessed_html` with duplicate blocks removed |
| **Algorithm** | SimHash on character 5-gram shingles of each content block |
| **Similarity threshold** | 0.85 (configurable) — blocks with ≥85% SimHash similarity AND within 30% line count are considered duplicates |
| **Minimum block size** | 3 lines (shorter blocks are never deduped) |

**Why SimHash, not SemHash?**

SemHash (2025) uses semantic embeddings (requires a model download, GPU preferred) — excellent for semantic deduplication but heavy for a microservice. SimHash is:

- Pure Python, zero ML dependencies
- O(1) comparison via Hamming distance on 128-bit fingerprints
- Perfectly adequate for detecting *structural* boilerplate (nav text, footers, sidebars that survived extraction)
- If you need semantic dedup, swap in SemHash as an alternative (see Alternative below)

**Alternative: SemHash** (for semantic dedup):
```python
from semhash import SemHash
index = SemHash.from_records(records=all_block_texts)
result = index.self_deduplicate(threshold=0.9)
# result.selected has the unique records
```
SemHash requires `pip install semhash` and will download a small sentence-transformer model on first run.

### Stage 5: Convert (HTML → Markdown)

| | Detail |
|---|--------|
| **Input** | `page.postprocessed_html` |
| **Output** | `page.markdown` (Markdown string) |
| **Library** | markdownify with `table_infer_header=True`, `heading_style="#"` (ATX) |
| **Table handling** | Simple tables: markdownify native. Complex tables (rowspan/colspan): markdownify with `table_infer_header=True`, fallback to raw HTML comment passthrough |
| **Code blocks** | Custom `Site2mdConverter` detects `language-*` classes on `<code>` inside `<pre>` and emits fenced code blocks with language annotation |

**Table strategy details** (see Section E):
- Tables with `<thead>`: markdownify handles natively
- Tables with `<th>` in first row: `table_infer_header=True` handles
- Tables with neither: `table_infer_header=True` treats first row as header
- Complex tables (rowspan/colspan): attempt conversion; if output is broken (<3 `|` chars), fall back to raw HTML in a comment block

### Stage 6: Assemble

| | Detail |
|---|--------|
| **Input** | All `PageResult` objects |
| **Output** | Single `done.md` file |
| **Sorting** | By crawl depth then URL path (`depth_then_path`) |
| **Section headers** | `##` for depth-0 pages, `###` for depth-1, etc. (adjustable `heading_base_level`) |
| **Separators** | `---` (horizontal rule) between pages |
| **Metadata** | Source URL, crawl date per section |
| **TOC** | Auto-generated from section headings |

(See Section C for full assembly strategy.)

---

## C. Markdown Assembly Strategy

### Page Ordering

Pages sorted by `(depth, url_path)`. This ensures:
1. Homepage/index pages come before subpages
2. Within same depth, alphabetical by URL path (which approximates site structure)

### Section Header Structure

```
## Introduction           ← depth=0, heading_base_level=2
**Source:** https://example.com/docs/intro

Content...

---

### Advanced Usage         ← depth=1, heading_base_level=2 → level 3
**Source:** https://example.com/docs/advanced

Content...
```

Heading level = `min(heading_base_level + page.depth, 6)`. This prevents heading explosion across deeply nested pages while keeping a logical hierarchy.

### Conflicting Heading Levels

The assemble stage **normalizes** all heading levels within a page relative to the page's depth-based starting level. A page with an `h1` at depth 2 becomes `h3`, `h2` becomes `h4`, etc. This prevents a deeply nested page from having the same heading level as the top-level index.

### Table of Contents

Generated at the top of `done.md`:

```markdown
# Table of Contents

- [Introduction](#introduction)
- [Advanced Usage](#advanced-usage)
```

Toggled by `AssemblyConfig.toc=True`.

### Page Separator

`---` (horizontal rule) between sections. Configurable via `AssemblyConfig.page_separator`.

### Metadata per Section

```
**Source:** https://example.com/docs/intro
**Crawled:** 2025-05-17T10:30:00Z
```

Toggled by `AssemblyConfig.include_metadata` and `AssemblyConfig.include_source_url`.

---

## D. Hidden Element Detection

### CSS-based Hidden Elements

| Pattern | Regex | What it catches |
|---------|-------|-----------------|
| `display:none` | `display\s*:\s*none` | Explicitly hidden elements |
| `visibility:hidden` | `visibility\s*:\s*hidden` | Invisible but layout-space elements |
| `opacity:0` | `opacity\s*:\s*0` | Transparent elements |
| Off-screen absolute | `position\s*:\s*absolute\s*;\s*left\s*:\s*-?\d{4,}px` | Elements shifted far left/right |
| `height:0` | `height\s*:\s*0` | Collapsed elements |
| `overflow:hidden;height:0` | Combined | Hidden containers |

**Important**: We only check inline `style` attributes (not external CSS), because we're processing raw HTML before rendering. External CSS rules aren't available without a browser. For full coverage, use a headless browser pre-render step (Puppeteer/Playwright) which would produce the computed styles.

### ARIA Hidden

All elements with `aria-hidden="true"` are removed. This is the most reliable signal — screen readers ignore these, and so should content extraction.

### ARIA Landmark Roles

Remove elements with these `role` attributes:
- `role="navigation"` (nav bars)
- `role="banner"` (headers)
- `role="contentinfo"` (footers)
- `role="complementary"` (sidebars)

### Ad Containers

Class/id regex patterns:

```python
# Classes
ad[-_]?(banner|container|slot|unit|wrapper)
advertisement
google[-_]ad
sponsored
promo[-_]?(box|sidebar|unit)

# IDs
^ad[-_]?
google_ad
ad_?
```

### Cookie Notices / Modals / Pop-ups

```python
# Class/id patterns
modal|popup|overlay|lightbox|cookie[-_]?notice|gdpr|consent[-_]?banner
```

These patterns err on the side of removal. For sites where modals contain real content, adjust the regex list.

---

## E. Table Extraction and Conversion

### Table Types

| Type | Detection | Strategy |
|------|-----------|----------|
| Simple `<table>` with `<thead>` | `el.find("thead")` | markdownify handles natively |
| `<th>` in first `<tr>` only | `el.find("tr").find("th")` | `table_infer_header=True` |
| No `<th>` at all | Neither above | `table_infer_header=True` treats first row as header |
| Complex (rowspan/colspan) | `el.find(attrs={"rowspan": True})` or `attrs={"colspan": True}` | Attempt markdownify conversion; if result has fewer than 3 pipe chars, fall back to raw HTML in a comment block |

### markdownify Options

```python
md(
    html,
    heading_style="#",        # ATX headings (# syntax)
    table_infer_header=True,  # first row becomes header row
    bullets="-",              # consistent bullet style
)
```

### Complex Table Fallback

When markdownify produces a broken table (common with rowspan/colspan), we fall back to preserving the raw HTML in a comment block:

```markdown
<!-- complex table, raw HTML -->
<table>
  <tr><td colspan="3">Wide cell</td></tr>
  ...
</table>
```

This ensures no data loss, at the cost of readability for that specific table.

---

## F. Performance Optimization

### Parallel Processing

```python
# CPU-bound stages (PreClean, PostProcess, Dedup) use ProcessPoolExecutor
pipeline.process_many(pages, max_workers=4)
```

The `ProcessPoolExecutor` in `Pipeline.process_many()` parallelizes stage processing across pages. Each page goes through all 6 stages, but different pages are processed concurrently.

**For truly large sites (1000+ pages):**

Consider a two-phase approach:
1. **Phase 1 — Extract** (stages 1-3): Parallelizable across pages, CPU-bound
2. **Phase 2 — Dedup + Assemble**: Must see all pages, largely sequential

```python
# Phase 1: Parallel extraction
from concurrent.futures import ProcessPoolExecutor

def extract_page(raw_html: str, url: str, depth: int, title: str) -> PageResult:
    page = PageResult(url=url, depth=depth, title=title, raw_html=raw_html)
    for stage in [PreCleanStage(), ExtractStage(), PostProcessStage()]:
        page = stage(page)
    return page

with ProcessPoolExecutor(max_workers=8) as pool:
    results = list(pool.map(extract_page, pages_data))

# Phase 2: Sequential dedup (needs global state) + convert + assemble
dedup = DedupStage()
convert = ConvertStage()
for page in results:
    page = dedup(page)
    page = convert(page)
```

### Memory Management

For 1000+ page sites:

1. **Stream to disk**: Write each page's markdown to a temp file immediately after conversion. Assemble reads from temp files, not memory.

```python
import tempfile

def convert_and_spill(page: PageResult, tmpdir: Path) -> Path:
    """Convert page and spill to disk to free memory."""
    page = ConvertStage()(page)
    path = tmpdir / f"{hashlib.sha256(page.url.encode()).hexdigest()[:12]}.md"
    path.write_text(page.markdown)
    page.markdown = ""  # free memory
    page.metadata["_spill_path"] = str(path)
    return page
```

2. **Batch dedup**: Process pages in batches of ~200 for SimHash comparison to limit `O(n²)` fingerprint comparisons.

```python
DEDUP_BATCH_SIZE = 200

for i in range(0, len(all_fingerprints), DEDUP_BATCH_SIZE):
    batch = all_fingerprints[i:i + DEDUP_BATCH_SIZE]
    # compare within batch and against existing global fingerprints
```

3. **Generator pattern**: Use generators instead of lists where possible to reduce peak memory.

### Caching

Cache extraction results keyed by `(url, content_hash)` to skip re-processing unchanged pages:

```python
import hashlib

def content_hash(html: str) -> str:
    return hashlib.sha256(html.encode()).hexdigest()[:16]

# Cache hit check before pipeline
cached = cache.get(url)
if cached and cached.content_hash == content_hash(page.raw_html):
    return cached.page_result
```

For production use, consider `diskcache` or Redis as the cache backend.

### Async Considerations

The current pipeline is synchronous and CPU-bound (BeautifulSoup/lxml parsing). For I/O-bound work (fetching pages), use `asyncio` with `aiohttp` in the crawler layer, then hand off to the synchronous pipeline. Mixing `asyncio` with CPU-bound `BeautifulSoup` provides no benefit — use `ProcessPoolExecutor` for CPU parallelism instead.

---

## Dependencies

```
# Core
trafilatura>=2.0          # Primary content extraction
readability-lxml>=0.8     # Fallback extraction
beautifulsoup4>=4.12      # HTML parsing & structural fixes
lxml>=5.0                 # Fast HTML parser backend
markdownify>=0.14         # HTML → Markdown conversion

# Dedup (lightweight, pure Python)
# SimHash implementation included in pipeline (no extra dependency)

# Alternative dedup (heavier, semantic)
# semhash>=0.1             # Semantic dedup with embeddings (optional)
```

Install:
```bash
pip install trafilatura readability-lxml beautifulsoup4 lxml markdownify
```