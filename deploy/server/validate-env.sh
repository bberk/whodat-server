#!/usr/bin/env bash
# Reject a Grafana bind address that would publish the dashboard beyond the LAN.
#
# Usage: validate-env.sh [env-file]
#
# The environment variable wins over the file, matching Compose's precedence. Only a private
# RFC 1918 IPv4 address is accepted: 10.0.0.0/8, 172.16.0.0/12, or 192.168.0.0/16. This rejects
# 0.0.0.0 (every interface), public addresses, IPv6, hostnames, and malformed values.
set -euo pipefail

fail() {
  printf 'validate-env.sh: %s\n' "$*" >&2
  exit 1
}

value="${GRAFANA_BIND_ADDRESS:-}"
if [[ -z "$value" ]]; then
  env_file="${1:-}"
  if [[ -n "$env_file" && -r "$env_file" ]]; then
    value="$(sed -n -E 's/^(export )?GRAFANA_BIND_ADDRESS=//p' "$env_file" | tail -n 1)"
    value="${value%$'\r'}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
  fi
fi

[[ -n "$value" ]] || fail "GRAFANA_BIND_ADDRESS is required; set the server's LAN address"

octet='(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])'
if [[ "$value" =~ ^10\.${octet}\.${octet}\.${octet}$ ]] ||
  [[ "$value" =~ ^192\.168\.${octet}\.${octet}$ ]] ||
  [[ "$value" =~ ^172\.(1[6-9]|2[0-9]|3[01])\.${octet}\.${octet}$ ]]; then
  exit 0
fi

fail "GRAFANA_BIND_ADDRESS must be a private RFC 1918 IPv4 address; got '$value'"
