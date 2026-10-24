#!/usr/bin/env bash
# Update one DuckDNS A record with the server's detected public IPv4 address.
# Required environment: DOMAIN=<subdomain>.duckdns.org and DUCKDNS_TOKEN=<token>.
# The systemd service reads both from a root-owned EnvironmentFile and runs as duckdns.
set -euo pipefail

fail() {
  printf 'duckdns-update: %s\n' "$*" >&2
  exit 1
}

: "${DOMAIN:?Set DOMAIN to the full DuckDNS hostname}"
: "${DUCKDNS_TOKEN:?Set DUCKDNS_TOKEN}"

command -v curl >/dev/null 2>&1 || fail "curl is required"

case "$DOMAIN" in
  *.duckdns.org) duckdns_name="${DOMAIN%.duckdns.org}" ;;
  *) fail "DOMAIN must be a full <subdomain>.duckdns.org hostname" ;;
esac

[[ "$duckdns_name" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] ||
  fail "DOMAIN contains an invalid DuckDNS subdomain"
[[ "$DUCKDNS_TOKEN" =~ ^[A-Za-z0-9_-]+$ ]] || fail "DUCKDNS_TOKEN has an invalid format"

# Supply the token through stdin instead of process arguments. Empty ip= asks DuckDNS to use
# the request's source address; ipv4 makes that the public IPv4 used by the router forward.
response="$(
  curl --config - <<EOF
silent
show-error
fail
ipv4
connect-timeout = 10
max-time = 30
get
url = "https://www.duckdns.org/update"
data-urlencode = "domains=${duckdns_name}"
data-urlencode = "token=${DUCKDNS_TOKEN}"
data-urlencode = "ip="
EOF
)"

[[ "$response" == "OK" ]] || fail "DuckDNS did not accept the update"
printf 'DuckDNS updated %s\n' "$DOMAIN"
