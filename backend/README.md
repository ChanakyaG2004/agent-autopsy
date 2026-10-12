# Backend

The FastAPI application validates configurations, saves experiments, and executes `refund-v1` with exactly one supported scenario: `normal`, `timeout_after_commit`, or `permission_denied`. Run evidence is stored in PostgreSQL. The default driver is a deterministic baseline demo, not an LLM.

The [timeout-after-commit walkthrough](../docs/timeout-after-commit.md) explains one-shot response loss, unknown outcomes, and the separate recovery demo. The [permission and policy walkthrough](../docs/permission-and-policy.md) adds definitive denial and independent trajectory grading. Multi-scenario execution remains unsupported.

Each new execution receives a versioned deterministic ledger evaluation, independent of execution status and final answer text. See [refund evaluation](../docs/refund-evaluation.md) for checks, evidence validation, and the deliberately incorrect claim-only demo.

Tracing is opt-in. See [Phoenix tracing setup and design](../docs/phoenix-tracing.md) to start the local collector, enable export, and inspect normal/error traces. Application PostgreSQL remains independent of Phoenix's local trace store.

This application will own request validation, application data, agent execution, benchmark execution, and evaluation. The agent runner will remain separate from HTTP handlers so a local command and, eventually, a worker can invoke the same logic.

Application PostgreSQL will store benchmark definitions and experiment results. Phoenix will receive execution telemetry. Results will reference their traces by ID.

## Run locally

Use installed PostgreSQL 16 tools. From the repository root, start the isolated development database:

```bash
# Homebrew example; omit PG_BIN if the desired PostgreSQL tools are on PATH.
PG_BIN=/opt/homebrew/opt/postgresql@16/bin bash backend/scripts/start-postgres.sh
```

The script creates its own password-protected cluster under ignored `backend/.local/`, binds to localhost:55432, and creates `agent_autopsy` and `agent_autopsy_test`. Running it again reuses that cluster. These example credentials are for local development. It does not modify or start a system-wide database service.

Then initialize the schema and start the API:

```bash
cd backend
cp -n .env.example .env
uv sync --locked
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
```

Use Python 3.11 or newer. `uv sync` creates a project-local `.venv` and installs the versions recorded in `uv.lock`.

`.env.example` documents the development and test database URLs. To use an existing PostgreSQL service, create dedicated databases and set those URLs in `.env` instead of running the bootstrap. Environment files are ignored by Git. The application also has the example development URL as a local default.

Open http://127.0.0.1:8000/docs. `POST /experiments` saves a draft; GET listing and UUID retrieval load records. `POST /experiments/{id}/runs` synchronously executes with mode `demo` (baseline), `demo_reconcile` (scripted recovery), `demo_claim_only` (negative control), or configured `openai`. Scenario comes from the saved experiment, not a run-request override. GET run history defaults to 10 records, bounded at 20. Created runs return 201 even for failed executions; inspect `status`, `evaluation.verdict`, `recovery_evaluation.verdict`, `scenario`, and `fault_injected`. The validation-only endpoint remains available. `/` returns 404.

Optional real model mode uses `OPENAI_API_KEY` and `OPENAI_MODEL` in the backend environment. Choose a model that supports Responses function calling. Do not put the key in frontend environment variables. Real model requests can incur provider charges. No key is needed for the demo. The OpenAI adapter is tested with mocked SDK responses; live model behavior is not yet verified.

## Files

- `pyproject.toml`: project metadata, Python requirement, and direct dependencies.
- `uv.lock`: resolved dependency versions; commit it for reproducible installs.
- `.python-version`: selects Python 3.11 for local development with uv.
- `app/__init__.py`: marks `app` as a Python package.
- `app/main.py`: creates the FastAPI application. Uvicorn loads the `app` object from this module.
- `app/database.py`: connection pool, declarative base, and request-scoped sessions.
- `app/models.py`: experiments and agent_runs table mappings, foreign key, constraints, and indexes.
- `app/agent.py`: driver protocol, bounded loop, unknown-outcome feedback, baseline/recovery/claim-only scripts.
- `app/tools.py`: validated tools, isolated refund state, one-shot post-mutation response loss, and persistent pre-mutation permission denial.
- `app/providers.py`: optional OpenAI Responses adapter and environment configuration.
- `app/execution.py`: atomic run claim, short database transactions, execution orchestration.
- `app/evaluation.py`: strict evidence schema, independent fixed expectation, pure deterministic evaluator, and typed verdict/checks.
- `app/recovery.py`: versioned trajectory checks for verification reads, denied writes, final response presence, and evidence compatibility.
- `app/telemetry.py`: owned tracer provider, OpenInference span attributes, bounded background OTLP/HTTP export, and lifecycle shutdown.
- `app/schemas.py`: typed HTTP request and response contracts.
- `alembic.ini` and `migrations/`: explicit versioned database schema changes.
- `scripts/start-postgres.sh`: local-only native PostgreSQL bootstrap.
- `scripts/start-phoenix.sh` and `scripts/phoenix_http.py`: optional local Phoenix service with persistent ignored storage and only an HTTP listener.
- `scripts/trace_failure.py`: explicitly tagged rejected-tool diagnostic, without application database writes.
- `tests/test_experiment_validation.py`: checks the request boundary, including invalid values and local browser access.
- `tests/test_experiment_persistence.py`: real PostgreSQL integration tests, with a separate test database and rolled-back transactions.
- `tests/test_agent.py`: runner limits, tool safety, state evidence, and mocked provider behavior.
- `tests/test_telemetry.py`: trace hierarchy, model/demo distinction, selected attribute capture, and exporter failure isolation.
- `tests/test_evaluation.py`: correct/incorrect ledger cases, malformed evidence, fixed-oracle checks, and deterministic behavior.
- `tests/test_recovery_policy.py`: denial boundaries, independent grades, malformed evidence, blind retries, and verification counterexamples.
- `tests/test_timeout_recovery.py`: injection timing, one-shot behavior, hidden outcomes, verification reads, retry guards, and turn limits.

FastAPI defines request handling. Uvicorn is the HTTP server that receives connections and invokes the application. The `--reload` flag restarts the development server when Python files change; `--reload-dir app` limits watching to source files so dependency installs do not trigger restarts.

## Tests

```bash
uv run --env-file .env pytest
uv run --env-file .env alembic check
```

The PostgreSQL service and dedicated `_test` database must be available for persistence tests. Migration setup is automatic. Most cases roll back their data; the two-connection concurrency test commits its fixture and explicitly cleans it up. No SQLite substitution is used.

To stop only this local cluster, from the repository root:

```bash
/opt/homebrew/opt/postgresql@16/bin/pg_ctl -D backend/.local/postgres -m fast -w stop
```

See [the persistence walkthrough](../docs/experiment-persistence.md) for transactions, schema decisions, failure semantics, and migrations.
See [the execution walkthrough](../docs/agent-execution.md) for run lifecycle, provider boundaries, and crash limitations.
