# Backend image for Docker Compose. Dependencies are installed from the lockfile.
FROM python:3.15-alpine

COPY --from=ghcr.io/astral-sh/uv:0.13.5-alpine /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

RUN apk add --no-cache bash curl git github-cli tar && \
    curl -fsSL https://opencode.ai/install | bash

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    PATH="/root/.opencode/bin:${PATH}"

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock backend/
RUN cd backend && uv sync --frozen --no-dev

COPY backend backend/
COPY scripts scripts/

WORKDIR /app/backend

RUN uv sync --frozen --no-dev \
    && python -m pip uninstall -y pip \
    && rm -rf /root/.cache/uv

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
