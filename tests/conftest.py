from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def patch_redis_deps():
    with (
        patch("site2md.core.redis.init_redis", return_value=None),
        patch("site2md.core.redis.close_redis", return_value=None),
        patch("site2md.core.redis.check_redis_health", return_value={"status": "ok", "redis": "connected"}),
    ):
        yield
