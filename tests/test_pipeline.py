
import pytest

from site2md.core.security import validate_chunk_delimiter, validate_url_safety
from site2md.domain.models import CrawlJobStatus, PageResult
from site2md.pipeline.core import Pipeline
from site2md.pipeline.stages.assemble import AssembleStage
from site2md.pipeline.stages.convert import ConvertStage
from site2md.pipeline.stages.preclean import PreCleanStage


class TestCrawlJobStatus:
    def test_status_values(self):
        assert CrawlJobStatus.PENDING.value == "pending"
        assert CrawlJobStatus.RUNNING.value == "running"
        assert CrawlJobStatus.COMPLETED.value == "completed"


class TestUrlValidation:
    def test_valid_url(self):
        safe, err = validate_url_safety("https://example.com")
        assert safe is True
        assert err is None

    def test_private_ip_blocked(self):
        safe, err = validate_url_safety("http://192.168.1.1")
        assert safe is False

    def test_non_http_blocked(self):
        safe, err = validate_url_safety("file:///etc/passwd")
        assert safe is False

    def test_localhost_blocked(self):
        safe, err = validate_url_safety("http://127.0.0.1:8080")
        assert safe is False


class TestChunkDelimiter:
    def test_valid_delimiter(self):
        safe, err = validate_chunk_delimiter("\n><\n")
        assert safe is True

    def test_too_long_delimiter(self):
        safe, err = validate_chunk_delimiter("x" * 11)
        assert safe is False

    def test_empty_delimiter(self):
        safe, err = validate_chunk_delimiter("")
        assert safe is False


class TestPreClean:
    async def test_removes_scripts_and_styles(self):
        html = "<html><head><script>alert('xss')</script><style>.a{color:red}</style></head><body><p>Hello</p></body></html>"
        page = PageResult(url="http://test.com", raw_html=html)
        stage = PreCleanStage()
        result = await stage.process(page)
        assert "script" not in result.raw_html.lower()
        assert "style" not in result.raw_html.lower()
        assert "Hello" in result.raw_html

    async def test_removes_hidden_elements(self):
        html = '<html><body><div style="display:none">hidden</div><p>visible</p></body></html>'
        page = PageResult(url="http://test.com", raw_html=html)
        stage = PreCleanStage()
        result = await stage.process(page)
        assert "hidden" not in result.raw_html

    async def test_removes_cookie_notices(self):
        html = '<html><body><div class="cookie-banner">accept cookies</div><p>content</p></body></html>'
        page = PageResult(url="http://test.com", raw_html=html)
        stage = PreCleanStage()
        result = await stage.process(page)
        assert "accept cookies" not in result.raw_html


class TestPreCleanStage:
    @pytest.mark.asyncio
    async def test_process(self):
        html = "<html><head><script>alert(1)</script></head><body><p>Hello</p></body></html>"
        page = PageResult(url="http://test.com", raw_html=html)
        stage = PreCleanStage()
        result = await stage.process(page)
        assert "script" not in result.raw_html.lower()
        assert "Hello" in result.raw_html


class TestConvertStage:
    @pytest.mark.asyncio
    async def test_converts_html_to_markdown(self):
        page = PageResult(url="http://test.com", extracted_html="<h1>Title</h1><p>Text</p>")
        stage = ConvertStage()
        pages = await stage.process([page])
        assert "# Title" in pages[0].markdown
        assert "Text" in pages[0].markdown


class TestAssembleStage:
    @pytest.mark.asyncio
    async def test_generates_toc_and_markers(self):
        pages = [
            PageResult(url="http://test.com/page1", title="Page 1", depth=0, markdown="# Title\n\nContent here"),
            PageResult(url="http://test.com/page2", title="Page 2", depth=1, markdown="# Another\n\nMore content"),
        ]
        stage = AssembleStage()
        result = await stage.process(pages, "\n|||\n")
        assert "Table of Contents" in result
        assert "Page 1" in result
        assert "Page 2" in result


class TestPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_runs(self):
        pages = [
            PageResult(
                url="http://test.com/docs",
                raw_html="<html><body><h1>Test</h1><p>Hello world text here</p></body></html>",
            ),
        ]
        pipeline = Pipeline()
        markdown, processed, stats = await pipeline.run(pages)
        assert "Hello world text here" in markdown
        assert stats["success"] >= 1
