# Agent Autopsy

An incremental reliability testing platform for AI agents that take actions, using Arize Phoenix, OpenTelemetry, and OpenInference.

## Goal

Run tool-using agents against versioned scenarios, inject API failures, and compare the agent's claims with executed actions and actual state changes. The first test subject will be an order/refund agent. Phoenix will provide execution traces for investigating failures.

## Planned stack

- Frontend: Next.js, React, and TypeScript
- Backend: Python, FastAPI, Pydantic, and PostgreSQL
- AI observability: Arize Phoenix, OpenTelemetry, and OpenInference

## Current status

The frontend has an introductory page and an interactive experiment configuration form. The form calls FastAPI for runtime validation and displays loading, success, and error states. Experiment creation, persistence, agent execution, fault injection, and Phoenix integration are not implemented yet.

Development proceeds in small, explained steps, with a focus on understanding each design decision before expanding the system.

## Repository layout

```text
frontend/   Next.js page, typed components, and experiment form
backend/    FastAPI configuration validation and request-boundary tests
docs/       Architecture exercises and design decisions
```

See [frontend setup and first task](frontend/README.md) and [backend setup](backend/README.md) for commands and file explanations. Run the two development servers in separate terminals. PostgreSQL and Phoenix are not needed for this checkpoint.

## Next milestone

Review [the experiment validation walkthrough](docs/experiment-validation.md), then add PostgreSQL persistence and an experiment creation endpoint. Use the [architecture worksheet](docs/architecture.md) to record understanding as we work through examples.
