# Backend

The FastAPI application validates proposed experiment configurations. Persistence and execution will be added in later steps.

This application will own request validation, application data, agent execution, benchmark execution, and evaluation. The agent runner will remain separate from HTTP handlers so a local command and, eventually, a worker can invoke the same logic.

Application PostgreSQL will store benchmark definitions and experiment results. Phoenix will receive execution telemetry. Results will reference their traces by ID.

## Run locally

From the repository root:

```bash
cd backend
uv sync --locked
uv run uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
```

Use Python 3.11 or newer. `uv sync` creates a project-local `.venv` and installs the versions recorded in `uv.lock`.

Open http://127.0.0.1:8000/docs and try `POST /experiments/validate`. It accepts an experiment name, an agent-version label, and scenario keys. It returns HTTP 200 for a valid configuration or HTTP 422 for invalid input. It does not save or execute the configuration. A request to `/` returns 404.

## Files

- `pyproject.toml`: project metadata, Python requirement, and direct dependencies.
- `uv.lock`: resolved dependency versions; commit it for reproducible installs.
- `.python-version`: selects Python 3.11 for local development with uv.
- `app/__init__.py`: marks `app` as a Python package.
- `app/main.py`: creates the FastAPI application. Uvicorn loads the `app` object from this module.
- `tests/test_experiment_validation.py`: checks the request boundary, including invalid values and local browser access.

FastAPI defines request handling. Uvicorn is the HTTP server that receives connections and invokes the application. The `--reload` flag restarts the development server when Python files change; `--reload-dir app` limits watching to source files so dependency installs do not trigger restarts.

## Tests

```bash
uv run pytest
```

See [the validation walkthrough](../docs/experiment-validation.md) for the contract and frontend/backend request flow.
