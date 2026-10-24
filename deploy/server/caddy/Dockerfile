# Build a multi-architecture Caddy image with the DuckDNS DNS-01 provider pinned.
ARG CADDY_VERSION=2.10.2

FROM caddy:${CADDY_VERSION}-builder-alpine AS build
ARG CADDY_VERSION
ARG DUCKDNS_PLUGIN_VERSION=v0.5.0
RUN xcaddy build "v${CADDY_VERSION}" \
    --with "github.com/caddy-dns/duckdns@${DUCKDNS_PLUGIN_VERSION}"

FROM caddy:${CADDY_VERSION}-alpine
COPY --from=build /usr/bin/caddy /usr/bin/caddy
# Baked in because the remote daemon cannot read bind mounts on the laptop.
COPY Caddyfile /etc/caddy/Caddyfile
