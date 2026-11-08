# Trade agent image for OpenCode & Discord trade ingestion.
FROM python:3.15-alpine

COPY --from=ghcr.io/astral-sh/uv:0.13.5-alpine /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

RUN apk add --no-cache git github-cli

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock backend/
RUN cd backend && uv sync --frozen --no-dev

COPY backend backend/
COPY scripts scripts/

CMD ["python", "-m", "scripts.trade_agent.discord_trade_ingest", "--help"]
