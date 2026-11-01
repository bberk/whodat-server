# Bake the scrape configuration into the image. The supported deployment runs Compose against a
# remote Docker daemon, so a bind mount of a laptop path does not exist on the server and fails
# with "not a directory". Building the config in, as the Caddy image does, keeps the build context
# local and the running container self-contained.
FROM prom/prometheus:v3.15.1

COPY prometheus.yml /etc/prometheus/prometheus.yml
