from site2md.core.logging import get_logger
from site2md.domain.models import PageResult
from site2md.pipeline.stages.assemble import AssembleStage
from site2md.pipeline.stages.convert import ConvertStage
from site2md.pipeline.stages.dedup import DedupStage
from site2md.pipeline.stages.extract import ExtractStage
from site2md.pipeline.stages.postprocess import PostProcessStage
from site2md.pipeline.stages.preclean import PreCleanStage

logger = get_logger(__name__)


class Pipeline:
    def __init__(self):
        self.stages = [
            PreCleanStage(),
            ExtractStage(),
            PostProcessStage(),
        ]

    async def run(self, pages: list[PageResult], chunk_delimiter: str = "\n><\n") -> tuple[str, list[PageResult], dict]:
        stats = {"success": 0, "skip": 0, "error": 0, "durations": {}}
        processed = []

        for page in pages:
            try:
                for stage in self.stages:
                    page = await stage.process(page)
                processed.append(page)
                stats["success"] += 1
            except Exception as e:
                logger.warning("Page processing failed", extra={"url": page.url, "error": str(e)})
                page.skipped = True
                page.skip_reason = str(e)
                processed.append(page)
                stats["error"] += 1

        dedup_stage = DedupStage()
        processed = await dedup_stage.process(processed)

        convert_stage = ConvertStage()
        processed = await convert_stage.process(processed)

        assemble_stage = AssembleStage()
        markdown = await assemble_stage.process(processed, chunk_delimiter)

        return markdown, processed, stats
