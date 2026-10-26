# Backend image for local Docker Compose. Dependencies are installed from the lockfile.
FROM python:3.15-alpine

COPY --from=ghcr.io/astral-sh/uv:0.13.5-alpine /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app/backend

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
RUN uv sync --frozen --no-dev \
    && python -m pip uninstall -y pip \
    && rm -rf /root/.cache/uv

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
