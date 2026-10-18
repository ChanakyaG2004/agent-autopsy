# Agent Autopsy

An incremental reliability testing platform for AI agents that take actions, using Arize Phoenix, OpenTelemetry, and OpenInference.

## Goal

Run tool-using agents against versioned scenarios, inject API failures, and compare the agent's claims with executed actions and actual state changes. The first test subject is an order/refund agent. Phoenix provides execution traces for investigating failures.

## Stack

- Frontend: Next.js, React, and TypeScript
- Backend: Python, FastAPI, Pydantic, and PostgreSQL
- AI observability: Arize Phoenix, OpenTelemetry, and OpenInference

## Current status

The frontend saves experiment drafts through FastAPI and lists recent records from PostgreSQL. A `refund-v1` experiment with exactly one supported scenario (`normal`, `timeout_after_commit`, or `permission_denied`) executes a bounded loop against an isolated simulated order. Runs persist the scenario, actual fault-injection flag, agent answer, tool actions, before/after state, and versioned ledger and recovery-policy evaluations. Execution status, refund correctness, and recovery behavior remain separate.

The first fault changes the refund ledger and then loses the tool response. The baseline demo stops with an unknown outcome; a recovery demo reads the order and completes without another refund request when the read confirms the full amount. Both can have a correct final ledger, but only the recovery demo passes the trajectory policy. Permission denial rejects writes before mutation; the recovery demo stops with a refusal, passing policy while leaving the refund goal unmet. The claim-only negative control still demonstrates completed execution with an incorrect ledger.

Optional OpenTelemetry tracing sends run, decision, tool, evaluator, and actual model-request spans to local Arize Phoenix; saved runs link to their traces. Demo drivers need no model key and emit no LLM spans. Ollama is the default real-model provider and runs installed tool-capable weights locally without an API key. Native measurements include model identity/digest, latency, usage coverage, and token counts in PostgreSQL and Phoenix. One real local validation passed in each supported scenario; an earlier model failure is preserved. OpenAI remains an optional adapter, unverified against a live paid provider. A versioned scripted benchmark runs the fixed task across all three scenarios and drivers, saving manifests, source/configuration fingerprints, item evidence, and separate aggregate counts. This first suite contains one distinct task and nine execution cells. Repeated live-model benchmark comparisons and general model-based answer evaluations are not implemented yet.

The comparison page at `/compare` shows saved executions side by side: independent verdicts, configuration changes, coverage-aware measurements, and trace links. A separate benchmark table compares scripted policies with explicit denominators and per-cell evidence. A single pair is not a reliability claim. See the [comparison walkthrough](docs/run-comparisons.md).

New runs also persist a tool-policy audit and typed-report grounding against agent-visible evidence. The two checks remain independent of business success. Historical answers stay ungraded; arbitrary prose is not semantically scored. See the [security and grounding walkthrough](docs/security-and-grounding.md).

Agent and benchmark submissions now use a durable PostgreSQL queue and separate workers. Request IDs prevent duplicate submissions; renewable leases fence stale publishers. Recovery retains saved outcomes, continues untouched benchmark cells, and explicitly marks unknown executions interrupted without replaying them. See the [worker design and walkthrough](docs/durable-workers.md).

Development proceeds in small, explained steps, with a focus on understanding each design decision before expanding the system.

## Repository layout

```text
frontend/   Next.js page, typed components, draft form, and saved run inspection
backend/    FastAPI, PostgreSQL, explicit agent loop, simulated tools, and tests
docs/       Architecture exercises and design decisions
```

See [frontend setup](frontend/README.md) and [backend/PostgreSQL setup](backend/README.md) for commands and file explanations. Run the two development servers in separate terminals. PostgreSQL is needed for application data. Follow the [Phoenix tracing walkthrough](docs/phoenix-tracing.md) to start the optional local collector and capture real traces.

## Next milestone

Use the [benchmark runner walkthrough](docs/benchmark-runner.md) for the fixed suite, API/CLI, reproducibility snapshots, failure semantics, and explicit metric denominators. The [permission and policy walkthrough](docs/permission-and-policy.md) explains the independent outcomes. The [local Ollama walkthrough](docs/ollama-local.md) documents native tool calling, local execution boundaries, measurements, and actual validation results. The earlier [OpenAI telemetry walkthrough](docs/model-telemetry.md) remains available. Next: release packaging with Docker Compose, CI, startup checks, and consolidated documentation. The application walkthrough is deferred while we work through release milestones one at a time. The [project rundown](docs/project-rundown.md), [execution walkthrough](docs/agent-execution.md), [tracing walkthrough](docs/phoenix-tracing.md), and [evaluation walkthrough](docs/refund-evaluation.md) document earlier checkpoints.
