import json

import pytest
import redis
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app


def test_ws_progress_streams_events():
    token = create_access_token("00000000-0000-0000-0000-000000000000")
    r = redis.from_url("redis://localhost:6379/0", decode_responses=True)

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/progress?token={token}") as ws:
            assert ws.receive_json() == {"type": "connected"}

            r.publish(
                "progress:00000000-0000-0000-0000-000000000000",
                json.dumps({"job": "job_search", "status": "completed", "detail": "5 new matches"}),
            )

            event = ws.receive_json()
            assert event["job"] == "job_search"
            assert event["status"] == "completed"
            assert event["detail"] == "5 new matches"

    r.close()


def test_ws_progress_rejects_missing_token():
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/progress"):
                pass
