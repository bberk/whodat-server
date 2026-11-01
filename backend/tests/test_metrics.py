"""Tests for the Prometheus scrape endpoint.

These cover the endpoint's contract with Prometheus and its absence from the public OpenAPI
surface. Request-metric label shape is asserted here because a high-cardinality label (the raw
path, a league id) is the failure mode that hurts a self-hosted Prometheus most.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app


def _scrape() -> str:
    """Return one ``/metrics`` scrape body from a fresh application."""
    response = TestClient(create_app()).get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    return response.text


def test_metrics_exposes_request_counter_using_route_templates() -> None:
    """A scrape includes the instrumented request counter keyed by a handler template."""
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200

    body = client.get("/metrics").text

    assert "# TYPE http_requests_total counter" in body
    assert 'handler="/health"' in body


def test_metrics_exposes_custom_provider_and_build_metrics() -> None:
    """Custom backend metrics are registered alongside the request metrics."""
    body = _scrape()

    assert "# TYPE app_build_info gauge" in body
    assert 'app_build_info{env="' in body
    assert "# TYPE app_provider_fetch_total counter" in body
    assert "# TYPE app_provider_fetch_duration_seconds histogram" in body


def test_metrics_scrape_is_not_instrumented_as_a_request() -> None:
    """Scrapes do not create their own request series, so scraping never inflates the graphs."""
    client = TestClient(create_app())
    client.get("/metrics")

    assert 'handler="/metrics"' not in client.get("/metrics").text


def test_metrics_is_absent_from_the_public_openapi_schema() -> None:
    """``/metrics`` is a scrape endpoint, not part of the typed API contract."""
    assert "/metrics" not in create_app().openapi()["paths"]


def test_base_request_counter_keeps_attribution_labels_off() -> None:
    """User and league ids live on their dedicated counters, not on every request series."""
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200

    lines = [
        line
        for line in client.get("/metrics").text.splitlines()
        if line.startswith("http_requests_total{")
    ]

    assert lines
    assert all("user_id=" not in line and "league_id=" not in line for line in lines)
