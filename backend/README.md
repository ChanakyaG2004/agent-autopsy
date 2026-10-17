# Backend

The FastAPI application validates configurations, saves experiments, and executes `refund-v1` with exactly one supported scenario: `normal`, `timeout_after_commit`, or `permission_denied`. Run evidence is stored in PostgreSQL. The API defaults to the deterministic demo when mode is omitted. The UI and validation CLI default to the local Ollama model.

The [timeout-after-commit walkthrough](../docs/timeout-after-commit.md) explains one-shot response loss, unknown outcomes, and the separate recovery demo. The [permission and policy walkthrough](../docs/permission-and-policy.md) adds definitive denial and independent trajectory grading. Multi-scenario execution remains unsupported.

Each new execution receives versioned deterministic ledger and recovery-policy evaluations, independent of execution status. The original ledger and recovery checks do not grade wording. New runs also receive tool-policy and typed-report grounding checks against agent-visible responses; unsupported free-form report formats remain not evaluable. See [refund evaluation](../docs/refund-evaluation.md) for checks, evidence validation, and the deliberately incorrect claim-only demo.

Tracing is opt-in. See [Phoenix tracing setup and design](../docs/phoenix-tracing.md) to start the local collector, enable export, and inspect normal/error traces. Application PostgreSQL remains independent of Phoenix's local trace store.

This application owns request validation, application data, agent execution, bounded scripted benchmark execution, and deterministic evaluation. The agent runner will remain separate from HTTP handlers so a local command and, eventually, a worker can invoke the same logic.

Application PostgreSQL stores benchmark definition snapshots, planned items, and experiment results. Phoenix will receive execution telemetry. Results will reference their traces by ID.

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

Open http://127.0.0.1:8000/docs. `POST /experiments` saves a draft; GET listing and UUID retrieval load records. `POST /experiments/{id}/runs` synchronously executes with mode `demo` (baseline), `demo_reconcile` (scripted recovery), `demo_claim_only` (negative control), `ollama` (native local model), or configured `openai`. Scenario comes from the saved experiment, not a run-request override. GET run history defaults to 10 records, bounded at 20. Created runs return 201 even for failed executions; inspect `status`, `evaluation.verdict`, `recovery_evaluation.verdict`, `scenario`, and `fault_injected`. The validation-only endpoint remains available. `/` returns 404.

Local real-model mode uses `OLLAMA_BASE_URL` and an installed tool-capable `OLLAMA_MODEL`, with no API key. See [local Ollama setup and real validation](../docs/ollama-local.md). Optional OpenAI mode uses `OPENAI_API_KEY` and `OPENAI_MODEL` in the backend environment. Choose a model that supports Responses function calling. Do not put the key in frontend environment variables. Real model requests can incur provider charges. No key is needed for the demo. The OpenAI adapter is tested with the installed SDK over mocked HTTP transport; live model behavior is not yet verified. [Model telemetry and validation](../docs/model-telemetry.md) explains per-request usage, partial aggregates, timing, and the explicit live-validation command.

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
- `app/providers.py`: provider selection and optional OpenAI Responses adapter.
- `app/ollama_provider.py`: loopback-only native local-model adapter, metadata checks, tool feedback, and measurements.
- `app/execution.py`: atomic run claim, short database transactions, execution orchestration.
- `app/evaluation.py`: strict evidence schema, independent fixed expectation, pure deterministic evaluator, and typed verdict/checks.
- `app/recovery.py`: versioned trajectory checks for verification reads, denied writes, final response presence, and evidence compatibility.
- `app/benchmark.py`: bounded sequential suite execution, independent aggregate counts, item-result recovery, report retrieval, and CLI.
- `app/benchmark_suite.py`: server-owned suite and reproducibility manifest fingerprints.
- `app/benchmark_schemas.py`: benchmark requests, persisted report contracts, and separate count fields.
- `app/model_telemetry.py`: strict token measurement contracts, usage validation, coverage, and known-subtotal aggregation.
- `app/validate_model.py`: configuration-only preflight and an explicit bounded model-backed validation command.
- `app/telemetry.py`: owned tracer provider, OpenInference span attributes, bounded background OTLP/HTTP export, and lifecycle shutdown.
- `app/schemas.py`: typed HTTP request and response contracts.
- `alembic.ini` and `migrations/`: explicit versioned database schema changes.
- `scripts/start-postgres.sh`: local-only native PostgreSQL bootstrap.
- `scripts/start-phoenix.sh` and `scripts/phoenix_http.py`: optional local Phoenix service with persistent ignored storage and only an HTTP listener.
- `scripts/trace_failure.py`: explicitly tagged rejected-tool diagnostic, without application database writes.
- `tests/test_experiment_validation.py`: checks the request boundary, including invalid values and local browser access.
- `tests/conftest.py`: shared isolated PostgreSQL fixtures and request-session overrides.
- `tests/test_benchmarks.py`: benchmark matrix, progress visibility, repetitions, snapshots, partial failures, evidence retention, and database boundaries.
- `tests/test_experiment_persistence.py`: real PostgreSQL integration tests, with a separate test database and rolled-back transactions.
- `tests/test_agent.py`: runner limits, tool safety, state evidence, and mocked provider behavior.
- `tests/test_ollama_provider.py`: local-only configuration, model preflight, native calls, feedback, measurement, and persistence boundaries.
- `tests/test_model_telemetry.py`: installed-SDK HTTP behavior, measured usage/timing, error privacy, durable measurements, and explicit validation boundaries.
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

The PostgreSQL service and dedicated `_test` database must be available for persistence tests. Migration setup is automatic. Most cases roll back their data; the two-connection concurrency and benchmark-progress tests commit their fixtures and explicitly clean them up. No SQLite substitution is used.

To stop only this local cluster, from the repository root:

```bash
/opt/homebrew/opt/postgresql@16/bin/pg_ctl -D backend/.local/postgres -m fast -w stop
```

See [the persistence walkthrough](../docs/experiment-persistence.md) for transactions, schema decisions, failure semantics, and migrations.
See [the execution walkthrough](../docs/agent-execution.md) for run lifecycle, provider boundaries, and crash limitations.

## Scripted benchmarks

See [the benchmark runner walkthrough](../docs/benchmark-runner.md). `GET /benchmark-suites` lists the single supported suite. `POST /benchmarks` accepts `{"repetitions":1}` and synchronously collects nine scripted executions. GET listing and UUID detail routes retain summary, manifest, and per-run evidence. No live model is selected by this suite.

```bash
uv run --env-file .env python -m app.benchmark --repetitions 1
```

One distinct task is exercised across three scenarios and three scripted drivers. Repetitions are bounded to 1–3; more repetitions do not create new tasks. Collection status is separate from agent and evaluation outcomes. Interrupted suites have no automatic resume yet. The full application walkthrough is deferred; automated regression checks continue during implementation.

## Model validation

```bash
# Checks local Ollama settings only; no provider or database request.
uv run --env-file .env python -m app.validate_model
# Explicitly runs the installed local model for one saved experiment.
uv run --env-file .env python -m app.validate_model --execute --scenario normal
```

`RunRead.model_telemetry` is null for scripted and historical runs. Ollama and OpenAI runs record provider-correct requested/reported model, request settings and fingerprints, per-attempt timing/status/usage, and coverage-aware known usage. Usage missing after a timeout is unknown, not zero. No dollar cost is estimated. The local provider has passed one real validation per supported scenario; optional OpenAI activation remains pending its credentials and model. The full application walkthrough remains deferred.

## Recorded comparisons

`GET /runs?limit=100&offset=0` lists saved run choices joined to experiment labels. `GET /run-comparisons?baseline_id=<uuid>&candidate_id=<uuid>` returns `recorded-runs-v2`: stored results, explicit eligibility checks, configuration differences, and permitted candidate-minus-baseline deltas. Identical IDs return 422; missing runs return 404. These routes never execute or regrade runs. The assurance milestone requires migration `7ba56d892c41`; existing rows remain ungraded. `app/comparisons.py` owns the rules, and `tests/test_comparisons.py` verifies eligibility, missing evidence, measurement boundaries, pagination, and read-only behavior. See the [comparison walkthrough](../docs/run-comparisons.md).

## Security and typed-report grounding

See the [design and learning walkthrough](../docs/security-and-grounding.md). `app/assurance.py` owns the strict final-report contract and pure tool-policy/grounding evaluators. New grades are saved independently in nullable JSONB columns, with separate Phoenix evaluator spans. The model validation CLI now emits `model-validation-v2` and checks both grades. The tool boundary remains strict; a blocked unsafe attempt can still fail policy. Grounding reads no hidden final state, and unsupported prose stays unavailable.
