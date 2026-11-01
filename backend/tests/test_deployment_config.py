"""Regression checks for the published-port boundary in the deployment files.

The backend's ``/metrics`` endpoint is unauthenticated by design and carries numeric user and
league attribution series. These tests pin the network boundary that keeps it internal: the
supported server stack never publishes the backend, Prometheus and the root development backend
bind loopback, Grafana binds a configured LAN address instead of every interface, and Caddy only
proxies the two intended backend paths. No test needs Docker or a network.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
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


def test_prometheus_retention_is_configurable_with_the_pinned_image() -> None:
    """Retention comes from the environment via the flag, so a smaller disk can lower it.

    The pinned image supports ``--storage.tsdb.retention.size`` (verified with a real server start
    that logged ``size=64GiB``). Keeping the flag in the command also stops the value from becoming
    a hardcoded config-file setting that a deployment cannot override.
    """
    config = yaml.safe_load(
        (REPO_ROOT / "deploy/server/monitoring/prometheus/prometheus.yml").read_text(
            encoding="utf-8"
        )
    )
    assert "storage" not in config

    services = _compose("deploy/server/docker-compose.yml")["services"]
    command = services["prometheus"]["command"]
    assert services["prometheus"]["image"] == "prom/prometheus:v3.15.1"
    assert "--storage.tsdb.retention.size=${PROMETHEUS_RETENTION_SIZE:-64GB}" in command
    assert "--storage.tsdb.wal-compression" in command


def _validate_env(
    tmp_path: Path, text: str, *, override: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the deploy preflight against a temporary env file."""
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    environment = {key: value for key, value in os.environ.items() if key != "GRAFANA_BIND_ADDRESS"}
    if override is not None:
        environment["GRAFANA_BIND_ADDRESS"] = override
    return subprocess.run(
        ["bash", str(REPO_ROOT / "deploy/server/validate-env.sh"), str(env_file)],
        capture_output=True,
        env=environment,
        check=False,
        text=True,
    )


@pytest.mark.parametrize("address", ["192.168.1.50", "10.0.0.5", "172.16.4.9", "172.31.255.254"])
def test_validate_env_accepts_private_lan_addresses(tmp_path: Path, address: str) -> None:
    """Every RFC 1918 range is valid for the LAN-only Grafana bind."""
    result = _validate_env(tmp_path, f"GRAFANA_BIND_ADDRESS={address}\n")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "address",
    ["0.0.0.0", "8.8.8.8", "172.32.0.1", "192.168.1.999", "::", "grafana.example.com"],
)
def test_validate_env_rejects_wildcard_and_public_addresses(tmp_path: Path, address: str) -> None:
    """A wildcard, public, IPv6, hostname, or malformed bind must fail before Compose starts."""
    result = _validate_env(tmp_path, f"GRAFANA_BIND_ADDRESS={address}\n")
    assert result.returncode != 0
    assert "GRAFANA_BIND_ADDRESS" in result.stderr


def test_validate_env_rejects_a_missing_address(tmp_path: Path) -> None:
    """An env file without the bind address fails closed instead of publishing everywhere."""
    result = _validate_env(tmp_path, "GRAFANA_ADMIN_USER=admin\n")
    assert result.returncode != 0
    assert "required" in result.stderr


def test_validate_env_prefers_the_environment_over_the_file(tmp_path: Path) -> None:
    """Compose gives the exported variable precedence, so the preflight must too."""
    result = _validate_env(tmp_path, "GRAFANA_BIND_ADDRESS=8.8.8.8\n", override="192.168.1.50")
    assert result.returncode == 0, result.stderr
