# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.7.8 AS uv
FROM python:3.11-slim-bookworm AS base
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./

FROM base AS dependencies
RUN uv sync --locked --no-dev --no-install-project

FROM base AS runtime
COPY --from=dependencies /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --uid 10001 --create-home app
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS observability
RUN uv sync --locked --no-dev --group observability --no-install-project
ENV PATH="/app/.venv/bin:$PATH" PHOENIX_WORKING_DIR=/data \
    PHOENIX_TELEMETRY_ENABLED=false PHOENIX_ALLOW_EXTERNAL_RESOURCES=false \
    PHOENIX_DISABLE_AGENT_ASSISTANT=true PHOENIX_ENABLE_MCP_SERVER=false
RUN useradd --uid 10001 --create-home app && mkdir /data && chown app /data
COPY scripts/phoenix_http.py ./scripts/phoenix_http.py
USER app
EXPOSE 6006
CMD ["python", "scripts/phoenix_http.py", "serve", "--host", "0.0.0.0", "--port", "6006", "--grpc-port", "0"]
