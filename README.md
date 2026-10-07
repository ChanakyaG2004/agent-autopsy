# Agent Autopsy

An incremental reliability testing platform for AI agents that take actions, using Arize Phoenix, OpenTelemetry, and OpenInference.

## Goal

Run tool-using agents against versioned scenarios, inject API failures, and compare the agent's claims with executed actions and actual state changes. The first test subject will be an order/refund agent. Phoenix will provide execution traces for investigating failures.

## Planned stack

- Frontend: Next.js, React, and TypeScript
- Backend: Python, FastAPI, Pydantic, and PostgreSQL
- AI observability: Arize Phoenix, OpenTelemetry, and OpenInference

## Current status

The frontend saves experiment drafts through FastAPI and lists recent records from PostgreSQL. The API validates configurations, persists drafts in a transaction, and supports bounded listing and retrieval by UUID. Alembic manages the schema. Agent execution, fault injection, and Phoenix integration are not implemented yet.

Development proceeds in small, explained steps, with a focus on understanding each design decision before expanding the system.

## Repository layout

```text
frontend/   Next.js page, typed components, draft form, and saved records
backend/    FastAPI, SQLAlchemy models, Alembic migrations, and API tests
docs/       Architecture exercises and design decisions
```

See [frontend setup](frontend/README.md) and [backend/PostgreSQL setup](backend/README.md) for commands and file explanations. Run the two development servers in separate terminals. PostgreSQL is needed for saving and reading experiments; Phoenix is introduced later.

## Next milestone

Review [the persistence walkthrough](docs/experiment-persistence.md), then introduce the explicit agent loop and simulated order/refund tools. Use the [architecture worksheet](docs/architecture.md) to record understanding as we work through examples.
