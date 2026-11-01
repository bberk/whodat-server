"""The application lifespan starts and stops the optional projection scheduler."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.main as main_module


def test_lifespan_starts_and_stops_the_projection_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scheduler returned by the startup hook is shut down when the app stops."""

    class FakeScheduler:
        def __init__(self) -> None:
            self.stopped = False

        def shutdown(self, wait: bool = False) -> None:
            self.stopped = True

    scheduler = FakeScheduler()
    monkeypatch.setattr(main_module, "start_projection_scheduler", lambda settings: scheduler)

    with TestClient(main_module.create_app()) as client:
        assert client.get("/health").status_code == 200

    assert scheduler.stopped
