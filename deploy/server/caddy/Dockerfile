# Build a multi-architecture Caddy image with the DuckDNS DNS-01 provider pinned.
ARG CADDY_VERSION=2.11.7

FROM caddy:${CADDY_VERSION}-builder-alpine AS build
ARG CADDY_VERSION
ARG DUCKDNS_PLUGIN_VERSION=v0.5.0
RUN xcaddy build "v${CADDY_VERSION}" \
    --with "github.com/caddy-dns/duckdns@${DUCKDNS_PLUGIN_VERSION}" \
    --replace "golang.org/x/net@v0.59.0=golang.org/x/net@v0.60.0"

FROM caddy:${CADDY_VERSION}-alpine
# The published Alpine base can lag its own security repository; pull the patched brotli and
# curl packages (CVE-2026-111497, CVE-2026-92392) without waiting for a new base tag.
RUN apk upgrade --no-cache
COPY --from=build /usr/bin/caddy /usr/bin/caddy
# Baked in because the remote daemon cannot read bind mounts on the laptop.
COPY Caddyfile /etc/caddy/Caddyfile
