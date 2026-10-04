# Agent Autopsy

An incremental project exploring AI agent reliability and observability with Arize Phoenix, OpenTelemetry, and OpenInference.

## Goal

Run tool-using agents against versioned benchmarks, inspect their traces, evaluate behavior, and compare changes. Later phases will introduce controlled fault injection, security benchmarks, failure clustering, and regression checks.

## Planned stack

- Frontend: Next.js, React, and TypeScript
- Backend: Python, FastAPI, Pydantic, and PostgreSQL
- AI observability: Arize Phoenix, OpenTelemetry, and OpenInference

## Current status

Phase 0: architecture and repository setup. No application functionality has been implemented yet.

Development proceeds in small, explained steps, with a focus on understanding each design decision before expanding the system.

## Repository layout

```text
frontend/   Next.js UI (planned; not initialized)
backend/    Python API and execution logic (planned; not initialized)
docs/       Architecture exercises and design decisions
```

The frontend and backend folders currently contain responsibility notes. There are no dependencies to install or services to start yet.

## Next milestone

Complete the [architecture worksheet](docs/architecture.md), review the data and execution boundaries, then initialize the frontend for the first manually written page.
