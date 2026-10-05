# Agent Autopsy

An incremental reliability testing platform for AI agents that take actions, using Arize Phoenix, OpenTelemetry, and OpenInference.

## Goal

Run tool-using agents against versioned scenarios, inject API failures, and compare the agent's claims with executed actions and actual state changes. The first test subject will be an order/refund agent. Phoenix will provide execution traces for investigating failures.

## Planned stack

- Frontend: Next.js, React, and TypeScript
- Backend: Python, FastAPI, Pydantic, and PostgreSQL
- AI observability: Arize Phoenix, OpenTelemetry, and OpenInference

## Current status

First checkpoint: frontend and backend development scaffolding. Experiment creation, persistence, agent execution, fault injection, and Phoenix integration are not implemented yet.

Development proceeds in small, explained steps, with a focus on understanding each design decision before expanding the system.

## Repository layout

```text
frontend/   Next.js App Router starter (React + TypeScript)
backend/    FastAPI application entry point
docs/       Architecture exercises and design decisions
```

See [frontend setup and first task](frontend/README.md) and [backend setup](backend/README.md) for commands and file explanations. Run the two development servers in separate terminals. PostgreSQL and Phoenix are not needed for this checkpoint.

## Next milestone

Write and review the first page, then build a typed component and an experiment form. The first complete workflow will send an experiment request from the browser to FastAPI, validate it, and persist it in PostgreSQL. Use the [architecture worksheet](docs/architecture.md) to record understanding as we work through examples.
