# MeshHeal control plane: collector + controller, rule scorer only (no torch, so the image stays small).
# Build from the repository root:   docker build -f deploy/Dockerfile -t meshheal-controlplane:0.7.1 .
# Run a component by naming its module:
#   docker run --rm meshheal-controlplane:0.7.1 controlplane.run --help
#   docker run --rm meshheal-controlplane:0.7.1 controlplane.collect --help
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY deploy/requirements-runtime.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY meshheal_controlplane/controlplane /app/controlplane
COPY meshheal_controlplane/playbooks /app/playbooks
# the agent that pushes this cluster's snapshots and decisions to a fleet API (stdlib only)
COPY dashboard /app/dashboard
RUN rm -rf /app/dashboard/tests

# a fixed non-root user, so a Kubernetes runAsNonRoot policy can verify it
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin meshheal
USER 10001

EXPOSE 9102
ENTRYPOINT ["python", "-m"]
CMD ["controlplane.run", "--help"]
