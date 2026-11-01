# Bake provisioning and dashboards into the image for the same reason as the Prometheus image:
# the supported deployment's Docker daemon is on the server and cannot see a path from the laptop
# that runs manage.sh. Dashboards live outside /var/lib/grafana so the state volume cannot shadow
# them.
FROM grafana/grafana:13.3.0

COPY provisioning /etc/grafana/provisioning
COPY dashboards /etc/grafana/dashboards
