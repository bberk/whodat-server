"""Regression checks for the published-port boundary in the deployment files.

The backend's ``/metrics`` endpoint is unauthenticated by design and carries numeric user and
league attribution series. These tests pin the network boundary that keeps it internal: the
supported server stack never publishes the backend, Prometheus and the root development backend
bind loopback, Grafana binds a configured LAN address instead of every interface, and Caddy only
proxies the two intended backend paths. No test needs Docker or a network.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _compose(relative_path: str) -> dict[str, object]:
    """Parse a Compose file from the repository without expanding its variables."""
    document = yaml.safe_load((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_root_compose_backend_binds_loopback_only() -> None:
    """The local/production-style stack must not expose the unauthenticated metrics endpoint."""
    services = _compose("docker-compose.yml")["services"]
    assert isinstance(services, dict)

    backend_ports = services["backend"]["ports"]
    assert backend_ports
    assert all(port.startswith("127.0.0.1:") for port in backend_ports)


def test_server_compose_publishes_no_backend_or_exporter_port() -> None:
    """The supported server stack reaches the backend only through the Compose network."""
    services = _compose("deploy/server/docker-compose.yml")["services"]
    assert isinstance(services, dict)

    assert "ports" not in services["backend"]
    assert "ports" not in services["node-exporter"]


def test_server_compose_prometheus_binds_loopback_only() -> None:
    """Prometheus has no authentication, so only an SSH tunnel may reach its UI."""
    services = _compose("deploy/server/docker-compose.yml")["services"]
    assert isinstance(services, dict)

    assert services["prometheus"]["ports"] == ["127.0.0.1:9090:9090"]


def test_server_compose_grafana_binds_the_configured_lan_address() -> None:
    """Grafana must never fall back to an all-interface bind when the address is missing."""
    services = _compose("deploy/server/docker-compose.yml")["services"]
    assert isinstance(services, dict)

    grafana_ports = services["grafana"]["ports"]
    assert len(grafana_ports) == 1
    published = grafana_ports[0]
    assert published.startswith("${GRAFANA_BIND_ADDRESS:")
    assert "0.0.0.0" not in published


def test_caddy_proxies_only_api_and_health_to_the_backend() -> None:
    """Caddy must not create a public route for /metrics or any other backend path."""
    caddyfile = (REPO_ROOT / "deploy/server/caddy/Caddyfile").read_text(encoding="utf-8")

    handlers = re.findall(r"^\s*handle\s+(/[^\s{]*)\s*\{", caddyfile, flags=re.MULTILINE)
    assert handlers == ["/api/*", "/health"]
    assert "/metrics" not in caddyfile


def test_prometheus_keeps_size_retention_with_the_pinned_image() -> None:
    """The config-file retention block needs an image that supports it.

    Prometheus v3.15.1 accepts this block (verified with ``promtool check config`` and a real
    server start that logged ``size=64GiB``). Pinning the image here makes a downgrade to a
    version without the block fail loudly instead of at container start on the server.
    """
    config = yaml.safe_load(
        (REPO_ROOT / "deploy/server/monitoring/prometheus/prometheus.yml").read_text(
            encoding="utf-8"
        )
    )
    assert config["storage"]["tsdb"]["retention"]["size"] == "64GB"

    services = _compose("deploy/server/docker-compose.yml")["services"]
    assert services["prometheus"]["image"] == "prom/prometheus:v3.15.1"
    assert "--storage.tsdb.wal-compression" in services["prometheus"]["command"]
