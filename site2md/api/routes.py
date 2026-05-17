import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from site2md.core.redis import get_redis as _get_redis
from site2md.models.schemas import CrawlRequest
from site2md.services.crawl_service import CrawlService


def get_redis():
    return _get_redis()

router = APIRouter(prefix="/crawl", tags=["Crawl"])


def _problem_response(code: int, type_: str, title: str, detail: str, instance: str) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        content={"type": type_, "title": title, "status": code, "detail": detail, "instance": instance},
        headers={"Content-Type": "application/problem+json"},
    )


@router.post("", status_code=202)
async def create_crawl(request: Request):
    try:
        body = await request.json()
        crawl_req = CrawlRequest.model_validate(body)
    except Exception as e:
        return _problem_response(422, "invalid-url", "Validation Error", str(e), str(request.url.path))

    r = await get_redis()
    service = CrawlService(r)
    job = await service.create_crawl(
        url=crawl_req.url,
        max_depth=crawl_req.max_depth,
        render_js=crawl_req.render_js,
        chunk_delimiter=crawl_req.chunk_delimiter,
    )
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "created_at": job.created_at.isoformat(),
        "url": job.url,
    }


@router.get("/{job_id}/status")
async def get_status(request: Request, job_id: str):
    r = await get_redis()
    service = CrawlService(r)
    try:
        status = await service.get_status(job_id)
    except CrawlService.NotFoundError:
        return _problem_response(404, "job-not-found", "Job Not Found", f"Job {job_id} not found", str(request.url.path))
    return status.model_dump()


@router.get("/{job_id}/result")
async def get_result(request: Request, job_id: str):
    r = await get_redis()
    service = CrawlService(r)
    try:
        result = await service.get_result(job_id)
    except CrawlService.NotFoundError:
        return _problem_response(404, "job-not-found", "Job Not Found", f"Job {job_id} not found", str(request.url.path))
    except CrawlService.JobNotCompleted:
        return _problem_response(
            409, "job-not-completed", "Job Not Completed",
            f"Job {job_id} is not yet completed", str(request.url.path),
        )
    except CrawlService.ResultExpired:
        return _problem_response(
            410, "result-expired", "Result Expired",
            f"Result for job {job_id} has expired", str(request.url.path),
        )
    return JSONResponse(content=result, media_type="text/markdown")


@router.delete("/{job_id}")
async def delete_crawl(request: Request, job_id: str):
    r = await get_redis()
    service = CrawlService(r)
    try:
        await service.cancel_crawl(job_id)
    except CrawlService.NotFoundError:
        return _problem_response(404, "job-not-found", "Job Not Found", f"Job {job_id} not found", str(request.url.path))
    except CrawlService.JobAlreadyCompleted:
        return _problem_response(
            409, "job-already-completed", "Job Already Completed",
            f"Job {job_id} is already completed", str(request.url.path),
        )
    except CrawlService.JobAlreadyCancelled:
        return _problem_response(
            409, "job-already-cancelled", "Job Already Cancelled",
            f"Job {job_id} is already cancelled", str(request.url.path),
        )
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/{job_id}/events")
async def sse_events(request: Request, job_id: str):
    r = await get_redis()
    service = CrawlService(r)

    exists = await service.job_exists(job_id)
    if not exists:
        return _problem_response(404, "job-not-found", "Job Not Found", f"Job {job_id} not found", str(request.url.path))

    async def event_generator():
        pubsub = r.pubsub()
        await pubsub.subscribe(f"crawl:{job_id}:progress")
        yield f"event: connected\ndata: {{\"job_id\": \"{job_id}\"}}\n\n"
        try:
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if msg and msg["type"] == "message":
                    data = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
                    yield f"event: progress\ndata: {data}\n\n"
                else:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(f"crawl:{job_id}:progress")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
