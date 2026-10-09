# Agent Autopsy

An incremental reliability testing platform for AI agents that take actions, using Arize Phoenix, OpenTelemetry, and OpenInference.

## Goal

Run tool-using agents against versioned scenarios, inject API failures, and compare the agent's claims with executed actions and actual state changes. The first test subject will be an order/refund agent. Phoenix will provide execution traces for investigating failures.

## Planned stack

- Frontend: Next.js, React, and TypeScript
- Backend: Python, FastAPI, Pydantic, and PostgreSQL
- AI observability: Arize Phoenix, OpenTelemetry, and OpenInference

## Current status

The frontend saves experiment drafts through FastAPI and lists recent records from PostgreSQL. A `refund-v1` experiment with only `normal` selected can execute a bounded tool loop against an isolated simulated order. Runs persist the agent's answer, tool actions, and before/after state. Optional OpenTelemetry tracing sends run, decision, tool, and actual model-request spans to local Arize Phoenix using OpenInference conventions; saved runs link to their traces. The deterministic demo needs no model key and emits no LLM spans. An optional OpenAI Responses adapter requires backend configuration; it has mocked tests but has not been verified against a live model. Fault injection and automated evaluations are not implemented yet.

Development proceeds in small, explained steps, with a focus on understanding each design decision before expanding the system.

## Repository layout

```text
frontend/   Next.js page, typed components, draft form, and saved run inspection
backend/    FastAPI, PostgreSQL, explicit agent loop, simulated tools, and tests
docs/       Architecture exercises and design decisions
```

See [frontend setup](frontend/README.md) and [backend/PostgreSQL setup](backend/README.md) for commands and file explanations. Run the two development servers in separate terminals. PostgreSQL is needed for application data. Follow the [Phoenix tracing walkthrough](docs/phoenix-tracing.md) to start the optional local collector and capture real traces.

## Next milestone

Review a normal and rejected-tool trace using the [tracing walkthrough](docs/phoenix-tracing.md). Next, write one deterministic state-based evaluator, then introduce timeout-after-commit and permission-denied scenarios. The [project rundown](docs/project-rundown.md) and [execution walkthrough](docs/agent-execution.md) document the preceding checkpoints. Use the [architecture worksheet](docs/architecture.md) to record understanding as we work through examples.
