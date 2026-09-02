from __future__ import annotations

import pytest


@pytest.fixture
def valid_env() -> dict[str, str]:
    return {
        "DAYTONA_API_KEY": "daytona-key-test",
        "SNAPSHOT_NAME": "snapshot-test",
        "CURSOR_API_KEY": "cursor-key-test",
        "CURSOR_AGENT_WORKER_ID": "worker-123",
        "CURSOR_POOL": "pool-test",
        "CURSOR_REQUEST_ID": "request-456",
    }
