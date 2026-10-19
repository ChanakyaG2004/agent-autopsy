# Run and operate the local release

This is the current startup reference. Earlier walkthroughs explain incremental checkpoints. The release is a localhost portfolio/demo application with simulated orders, not a public payment service. It has no authentication, tenant isolation, or hosted deployment.

## Basic Docker demo

Prerequisites: Docker with Compose v2, and Python 3 for the host acceptance script. Run from the repository root:

```bash
docker compose up --build --wait
python3 scripts/smoke.py
```

Open `http://127.0.0.1:3000`. Save a draft with version `refund-v1` and exactly one scenario. Expand its run panel, select a **scripted demo** driver, and queue a simulated refund. The default Ollama choice requires the optional model service below. On `/compare`, **Queue scripted benchmark (9 cells)** exercises all three scripted policies and scenarios.

The base stack contains PostgreSQL, a one-shot migration, API, worker, and frontend. Database health gates migration; successful migration gates API startup; API readiness gates worker/frontend startup. Compose's [`service_healthy` and `service_completed_successfully` conditions](https://docs.docker.com/compose/how-tos/startup-order/) express initial startup dependencies, not a distributed availability guarantee.

Published ports bind to `127.0.0.1`. PostgreSQL has no host port. Example credentials belong only to this local stack. Docker build contexts exclude `.env` files, existing databases, installed host dependencies, and API keys. Application containers run as non-root users. Dependencies install from committed lockfiles; base image tags still need rebuilding for compatible patch updates. The backend installation follows the [uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/).

API and worker share backend code/settings but are separate processes. Restarting the API does not cancel accepted work. The worker container's running state proves process life, not job progress: read receipts or run the smoke check. See [leases and recovery](durable-workers.md).

## Add Phoenix tracing

```bash
AGENT_AUTOPSY_TRACING_ENABLED=true docker compose --profile observability up --build --wait
python3 scripts/smoke.py
```

Phoenix opens at `http://127.0.0.1:6006`. Run the smoke test after enabling tracing; historical untraced runs do not acquire traces. The collector uses locked observability dependencies, the HTTP-only launcher, and a separate persistent SQLite volume. Optional telemetry and external resources are disabled. Trace delivery is best effort; missing Phoenix diagnostics cannot change PostgreSQL grades.

Follow **Phoenix trace** from a saved run or benchmark cell. The `job.execute` root identifies job and attempt. Nested agent, decision, tool, model, and evaluator spans show different parts of execution. Scripted drivers have no model spans or token usage.

## Add free local Ollama weights in Docker

The optional override supplies Ollama. The worker shares its network namespace and calls `127.0.0.1:11434`; no model port is published. This preserves the adapter's loopback-only boundary without allowing arbitrary remote inference URLs.

```bash
docker compose -f compose.yaml -f compose.ollama.yaml up --build --wait
docker compose -f compose.yaml -f compose.ollama.yaml exec ollama ollama pull llama3.1:latest
docker compose -f compose.yaml -f compose.ollama.yaml exec worker python -m app.preflight --ollama
python3 scripts/smoke.py --model --timeout 420
```

Pulling weights is an explicit multi-gigabyte download into `ollama-models`. The base stack never downloads weights or requests inference. A healthy Ollama server does not imply an installed tool-capable model; preflight checks that separately. Choose Ollama in the UI after it passes. Linux containers on a Mac do not use native Metal acceleration; native setup is generally better for interactive model work. Supply enough memory for weights and context. A failed/slow observation stays saved.

Combine the override with `--profile observability` and `AGENT_AUTOPSY_TRACING_ENABLED=true` for model traces. Preserve the same flags on subsequent commands. To return to the base worker, stop using the override before starting the base configuration. The shared network namespace is a single-worker local convenience, not a model-worker scaling design.

## Native development

Follow [backend setup](../backend/README.md) to initialize PostgreSQL and `.env`, and [frontend setup](../frontend/README.md) for Node dependencies. This path uses host Ollama and native acceleration.

```bash
# backend/, after uv sync --locked and PostgreSQL startup
uv run --env-file .env alembic upgrade head
uv run --env-file .env python -m app.preflight
uv run --env-file .env python -m app.preflight --ollama
```

Start separate terminals:

```bash
# API, backend/
uv run --env-file .env uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
# Worker, backend/
uv run --env-file .env python -m app.worker
# UI, frontend/
npm run dev -- --hostname 127.0.0.1 --port 3000
```

For traces, run `bash scripts/start-phoenix.sh` from `backend/` and enable `AGENT_AUTOPSY_TRACING_ENABLED=true` for both API and worker. Restart workers after backend code/model-setting changes: they intentionally stop claiming jobs when startup fingerprints become stale. Avoid running `next build` concurrently with the dev server against the same `.next` directory; stop the server or build in Docker.

From the repository root, `python3 scripts/smoke.py` tests the API and separate worker. `--model --timeout 420` adds three local Ollama observations. It creates saved demo records; it never deletes history or invokes OpenAI. Its repeated acceptance deliberately verifies the same request ID returns the same job; it does not retry model work. Exit 0 means every specified check passed; exit 1 means a check failed. Inspect saved evidence before submitting new work.

## Alternate ports

To coexist with native servers:

```bash
FRONTEND_PORT=3100 API_PORT=8100 PHOENIX_PORT=6106 docker compose -p agent-autopsy-release-check up --build --wait
python3 scripts/smoke.py --api-url http://127.0.0.1:8100
```

Open port 3100. Repeat variables/project name on later commands. Public API/trace URLs are frontend **build arguments**: they must reference host-accessible ports, not Docker service names. Changing them requires rebuilding the frontend. Backend services use internal DNS for PostgreSQL/Phoenix. Compose configures CORS to match the frontend port. Native CORS defaults to localhost/127.0.0.1:3000; set `AGENT_AUTOPSY_FRONTEND_ORIGINS` for another origin.

## Health, persistence, and shutdown

| Check | What it proves |
| --- | --- |
| `GET /health/live` | API responds without checking dependencies |
| `GET /health/ready` | Database responds and Alembic revision matches this checkout; 503 otherwise |
| `python -m app.preflight` | Same startup check, no inference |
| `python -m app.preflight --ollama` | Also verifies installed local tool-capable model metadata, no inference |
| `python3 scripts/smoke.py` | HTTP acceptance, separate worker, saved controls and comparison |

Optional model/Phoenix services are excluded from readiness so scripted work remains independent. Health responses omit database addresses and exception text.

```bash
docker compose ps
docker compose logs --tail 100 api worker
docker compose stop worker
docker compose start worker
docker compose down
```

Stopping a worker sends SIGTERM with up to five minutes for graceful drain. A hard kill or expired lease invokes conservative recovery, not blind replay. Unknown started runs become interrupted; untouched work can continue. Last-saved state is not proof of final state.

`down` preserves named data volumes. Do not add `--volumes` unless intentionally discarding records. Native development storage is separate and never mounted into Compose. Before upgrading, drain workers, back up PostgreSQL, rebuild the chosen checkout, apply migration, and start matching API/worker images. There is no zero-downtime migration guarantee. Downgrades that would erase job receipts or invalidate interrupted runs are refused.

## Troubleshooting

| Symptom | Inspect or correct |
| --- | --- |
| Cannot connect to Docker | Start Docker Engine/Desktop |
| Host port allocated | Stop the other server or use alternate ports and rebuild |
| API readiness 503 | Database logs, migration exit status, matching schema/checkout |
| Job remains queued | Worker logs; restart after source fingerprint drift |
| Job interrupted | Outcome may be unknown; automatic replay is unsafe |
| Model preflight fails | Service, installed tool-capable weights, configured model, memory |
| Missing trace | Enable worker export before execution and start collector |
| Browser fetch failure | Public build URL and CORS origin must match host ports |

## CI and release gate

The read-only GitHub Actions workflow runs PostgreSQL-backed backend tests; frontend tests, lint, type checking, and build; and a fresh base Compose stack plus HTTP acceptance. It captures diagnostics on failure and stops containers afterward. These are deterministic regression gates, not estimated model-reliability thresholds. CI needs no provider secret and downloads no weights. Real-model/browser observations are recorded separately in the [verification record](release-verification.md).
