#!/usr/bin/env bash
set -euo pipefail

backend_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$backend_dir"
export PHOENIX_WORKING_DIR="$backend_dir/.local/phoenix"
export PHOENIX_TELEMETRY_ENABLED=false
export PHOENIX_ALLOW_EXTERNAL_RESOURCES=false
export PHOENIX_DISABLE_AGENT_ASSISTANT=true
export PHOENIX_ENABLE_MCP_SERVER=false
mkdir -p "$PHOENIX_WORKING_DIR"
# OTLP/HTTP is sufficient; disable the separate gRPC listener.
exec uv run --locked --group observability python scripts/phoenix_http.py serve --host 127.0.0.1 --port 6006 --grpc-port 0
