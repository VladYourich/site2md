from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from prometheus_fastapi_instrumentator import Instrumentator

    from site2md.core.health import router as health_router

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    mock_crawl = MagicMock()
    mock_crawl.job_id = "test-job-id"
    mock_crawl.status = MagicMock(value="pending")
    mock_crawl.created_at = MagicMock(isoformat=lambda: "2026-05-17T00:00:00")
    mock_crawl.url = "https://example.com"

    mock_status = MagicMock()
    mock_status.model_dump = lambda: {  # noqa: E501
        "job_id": "test-job-id", "status": "pending", "url": "https://example.com",
        "pages_crawled": 0, "pages_total": None, "created_at": "2026-05-17",
        "started_at": None, "completed_at": None, "error": None, "failed_urls": [],
    }

    class NotFoundError(Exception):
        pass

    class JobNotCompleted(Exception):
        pass

    class ResultExpired(Exception):
        pass

    class JobAlreadyCompleted(Exception):
        pass

    class JobAlreadyCancelled(Exception):
        pass

    svc_instance = MagicMock()
    svc_instance.NotFoundError = NotFoundError
    svc_instance.JobNotCompleted = JobNotCompleted
    svc_instance.ResultExpired = ResultExpired
    svc_instance.JobAlreadyCompleted = JobAlreadyCompleted
    svc_instance.JobAlreadyCancelled = JobAlreadyCancelled
    svc_instance.create_crawl = AsyncMock(return_value=mock_crawl)
    svc_instance.get_status = AsyncMock(return_value=mock_status)
    svc_instance.get_result = AsyncMock(return_value="# Test markdown content")
    svc_instance.cancel_crawl = AsyncMock()
    svc_instance.job_exists = AsyncMock(return_value=False)

    mock_svc_cls = MagicMock(return_value=svc_instance)
    mock_svc_cls.NotFoundError = NotFoundError
    mock_svc_cls.JobNotCompleted = JobNotCompleted
    mock_svc_cls.ResultExpired = ResultExpired
    mock_svc_cls.JobAlreadyCompleted = JobAlreadyCompleted
    mock_svc_cls.JobAlreadyCancelled = JobAlreadyCancelled

    p1 = patch("site2md.api.routes._get_redis", return_value=AsyncMock())
    p2 = patch("site2md.api.routes.CrawlService", mock_svc_cls)

    p1.start()
    p2.start()

    from site2md.api.routes import router as api_router

    app = FastAPI(
        title="site2md", version="0.2.0", description="test",
        lifespan=lifespan, docs_url="/docs", openapi_url="/openapi.json",
    )
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)
    app.include_router(health_router, tags=["Health"])

    @app.get("/ready", tags=["Health"])
    async def readiness():
        return {"status": "ok", "redis": "connected"}

    app.include_router(api_router, prefix="/api/v1")

    yield TestClient(app), svc_instance

    p2.stop()
    p1.stop()


class TestHealthEndpoints:
    def test_health_returns_200(self, client):
        tc, _ = client
        assert tc.get("/health").status_code == 200

    def test_metrics_endpoint(self, client):
        tc, _ = client
        assert tc.get("/metrics").status_code == 200

    def test_docs_endpoint(self, client):
        tc, _ = client
        assert tc.get("/docs").status_code == 200

    def test_openapi_json(self, client):
        tc, _ = client
        data = tc.get("/openapi.json").json()
        assert data["info"]["title"] == "site2md"


class TestCrawlEndpoints:
    def test_post_crawl_validation_blocked_ip(self, client):
        tc, _ = client
        assert tc.post("/api/v1/crawl", json={"url": "http://192.168.1.1", "max_depth": 2}).status_code == 422

    def test_post_crawl_validation_no_scheme(self, client):
        tc, _ = client
        assert tc.post("/api/v1/crawl", json={"url": "example.com"}).status_code == 422

    def test_post_crawl_success(self, client):
        tc, svc = client
        resp = tc.post("/api/v1/crawl", json={"url": "https://example.com", "max_depth": 2})
        assert resp.status_code == 202
        assert resp.json()["job_id"] == "test-job-id"
        svc.create_crawl.assert_called_once()

    def test_get_status_success(self, client):
        tc, svc = client
        resp = tc.get("/api/v1/crawl/test-job-id/status")
        assert resp.status_code == 200
        svc.get_status.assert_called_once_with("test-job-id")

    def test_get_status_not_found(self, client):
        tc, svc = client
        svc.get_status.side_effect = svc.NotFoundError()
        resp = tc.get("/api/v1/crawl/nonexistent-id/status")
        assert resp.status_code == 404

    def test_get_result_not_completed(self, client):
        tc, svc = client
        svc.get_result.side_effect = svc.JobNotCompleted()
        resp = tc.get("/api/v1/crawl/test-job-id/result")
        assert resp.status_code == 409

    def test_get_result_not_found(self, client):
        tc, svc = client
        svc.get_result.side_effect = svc.NotFoundError()
        resp = tc.get("/api/v1/crawl/nonexistent-id/result")
        assert resp.status_code == 404

    def test_delete_crawl(self, client):
        tc, svc = client
        resp = tc.delete("/api/v1/crawl/test-job-id")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_delete_not_found(self, client):
        tc, svc = client
        svc.cancel_crawl.side_effect = svc.NotFoundError()
        resp = tc.delete("/api/v1/crawl/nonexistent-id")
        assert resp.status_code == 404

    def test_delete_already_cancelled(self, client):
        tc, svc = client
        svc.cancel_crawl.side_effect = svc.JobAlreadyCancelled()
        resp = tc.delete("/api/v1/crawl/test-job-id")
        assert resp.status_code == 409
