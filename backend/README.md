# Backend

The FastAPI application validates configurations and saves experiment drafts in PostgreSQL. Execution is not implemented yet.

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

Open http://127.0.0.1:8000/docs. `POST /experiments` returns 201 with a persisted draft, `GET /experiments` lists a bounded page, and `GET /experiments/{id}` retrieves one record. The validation-only endpoint remains available. Nothing executes an agent yet. A request to `/` returns 404.

## Files

- `pyproject.toml`: project metadata, Python requirement, and direct dependencies.
- `uv.lock`: resolved dependency versions; commit it for reproducible installs.
- `.python-version`: selects Python 3.11 for local development with uv.
- `app/__init__.py`: marks `app` as a Python package.
- `app/main.py`: creates the FastAPI application. Uvicorn loads the `app` object from this module.
- `app/database.py`: connection pool, declarative base, and request-scoped sessions.
- `app/models.py`: experiments table mapping, constraints, and creation-time index.
- `app/schemas.py`: typed HTTP request and response contracts.
- `alembic.ini` and `migrations/`: explicit versioned database schema changes.
- `scripts/start-postgres.sh`: local-only native PostgreSQL bootstrap.
- `tests/test_experiment_validation.py`: checks the request boundary, including invalid values and local browser access.
- `tests/test_experiment_persistence.py`: real PostgreSQL integration tests, with a separate test database and rolled-back transactions.

FastAPI defines request handling. Uvicorn is the HTTP server that receives connections and invokes the application. The `--reload` flag restarts the development server when Python files change; `--reload-dir app` limits watching to source files so dependency installs do not trigger restarts.

## Tests

```bash
uv run --env-file .env pytest
uv run --env-file .env alembic check
```

The PostgreSQL service and dedicated `_test` database must be available for persistence tests. Migration setup is automatic in the tests; each case rolls back its own data. No SQLite substitution is used.

To stop only this local cluster, from the repository root:

```bash
/opt/homebrew/opt/postgresql@16/bin/pg_ctl -D backend/.local/postgres -m fast -w stop
```

See [the persistence walkthrough](../docs/experiment-persistence.md) for transactions, schema decisions, failure semantics, and migrations.
