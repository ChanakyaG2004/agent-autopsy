# Phoenix tracing milestone

The existing execution path now emits real OpenTelemetry spans to a local Arize Phoenix collector. OpenInference attributes tell Phoenix whether an operation is an agent, a chain/decision, a tool, or an actual LLM request. Saved PostgreSQL runs store the corresponding trace ID.

## What a trace contains

One trace groups the work for one execution. Each span describes one operation with its own start/end time, attributes, status, and parent. The normal deterministic demo produces this tree:

```text
agent.run                          AGENT
├─ agent.decision (turn 1)          CHAIN
├─ tool.execute: get_order          TOOL
├─ agent.decision (turn 2)          CHAIN
├─ tool.execute: issue_refund       TOOL
└─ agent.decision (turn 3)          CHAIN
```

OpenTelemetry's current-span context makes these operations children of the active run. An actual OpenAI driver request adds `openai.responses` with kind `LLM` beneath its decision span. The deterministic demo makes no model requests and emits no LLM spans. Its trace shows software execution, not model quality or a benchmark score.

OpenTelemetry provides the tracing machinery and OTLP transport. OpenInference supplies AI-specific attribute conventions. Phoenix receives, stores, and renders the spans. These responsibilities are distinct; see the [OpenInference trace specification](https://github.com/Arize-ai/openinference/blob/main/spec/traces.md) and [Phoenix tracing explanation](https://arize.com/docs/phoenix/tracing/concepts-tracing/how-does-tracing-work).

## Local services and setup

Keep the existing PostgreSQL, API, and frontend setup. In another terminal, from the repository root:

```bash
bash backend/scripts/start-phoenix.sh
```

This installs the lockfile's optional `observability` dependency group and starts Phoenix at `http://127.0.0.1:6006`. Phoenix keeps its own SQLite trace database under ignored `backend/.local/phoenix/`. This does not replace or modify the application's PostgreSQL schema. Stop Phoenix with Ctrl+C.

The launcher disables Phoenix web telemetry, external-resource fetching, its assistant, and its MCP server for this local tracing exercise. Phoenix 20.23 starts gRPC on all interfaces, and port 0 selects an ephemeral port rather than disabling it. `scripts/phoenix_http.py` is a small runtime compatibility adapter that disables that unused listener without modifying installed package files. The HTTP listener is explicitly bound to loopback. Recheck this adapter when upgrading Phoenix. The startup banner still prints a gRPC URL with port 0, but the listener is disabled; only localhost:6006 should be listening for this process.

Enable application tracing in `backend/.env`:

```dotenv
AGENT_AUTOPSY_TRACING_ENABLED=true
PHOENIX_OTLP_ENDPOINT=http://127.0.0.1:6006/v1/traces
```

Restart the backend so its lifespan reads these settings:

```bash
cd backend
uv run --env-file .env alembic upgrade head
uv run --env-file .env uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
```

Tracing is disabled by default. No Phoenix service is required to use the application. No provider key or cloud account is required for tracing a demo. The collector destination is backend process configuration, never a request parameter. Remote collectors and authentication are outside this local milestone.

The frontend defaults to `http://127.0.0.1:6006` for trace links. `NEXT_PUBLIC_PHOENIX_BASE_URL` changes the browser-facing UI location; it is separate from the backend OTLP ingest endpoint. Restart the frontend after changing browser-visible environment values.

## Inspect a normal run

1. Create an experiment using `refund-v1` and only Normal execution.
2. Open its run panel and execute the deterministic demo.
3. Follow Open trace in Phoenix. Export is asynchronous, so a newly captured trace can take a moment to appear.
4. Select a tool span and inspect the validated arguments, returned state summary, status, and duration.
5. Inspect root attributes `agent.run_id`, `agent.experiment_id`, `agent.mode`, and `agent.version`. These connect telemetry to the saved configuration and result.
6. Reload the application and refresh run history. The trace ID/link is persisted, not reconstructed from browser memory.

Older rows have a null `trace_id`. The migration does not invent traces or alter historical evidence. A trace ID means capture was enabled; it is **not an export receipt**. A link can be unavailable if export failed or the trace was later removed from Phoenix.

## Inspect an intentionally failed trace

From `backend/`, with Phoenix running:

```bash
AGENT_AUTOPSY_TRACING_ENABLED=true uv run --locked python -m scripts.trace_failure
```

The script requests an unregistered tool. The same runner rejects it, and the tool-attempt span receives ERROR. The runner catches the error and returns normally, so the diagnostic explicitly marks the root ERROR as well. This prevents a handled exception from appearing as an entirely successful trace. The diagnostic is tagged `agent.diagnostic=true`, prints its trace ID, and creates no application experiment/run rows.

This is a controlled tool-guard diagnostic, not implementation of the planned timeout-after-commit or permission-denied scenarios. A failed execution and a failed business task remain different concepts. An agent can finish with an incorrect claim while all its spans are operationally OK; deterministic evaluation must identify that separate problem.

## Capture boundaries

Root spans contain correlation IDs, mode/version, the fixed task, and selected outcome fields. Tool spans contain validated sandbox arguments and a compact result: order ID, refunded cents, refund count. Invalid/unregistered names are normalized in tracing, and rejected argument payloads are not copied. Decision spans record the turn, allowlisted requested tool names, and whether a final answer was returned.

Model spans currently record provider/model labels, duration, and success/failure. They do not copy raw input history, output text, reasoning, API keys, or arbitrary provider exception payloads. Raw answer and executed-step evidence remain in the application run record under the preexisting behavior; this milestone does not add a general redaction system for that database.

No token or cost attributes are emitted. Phoenix may display zero totals for missing metrics in a demo; those displays are not measured usage for a real model. The optional model adapter is tested with mocked SDK responses; live-provider tracing remains unverified.

## Export and failure behavior

`app/telemetry.py` owns a tracer provider rather than changing OpenTelemetry's process-wide global provider. FastAPI lifespan configures it once and shuts it down on exit. A batch processor exports OTLP/HTTP in a background thread: queue size 512, batch size at most 64, scheduled every 500 ms. The exporter has a one-second network timeout; this is not a hard global execution deadline. Shutdown may wait for queued export work.

The run request does not flush spans or wait for collector acknowledgement. Slow/unavailable export does not alter the agent result. SDK exporter errors are logged. The queue is bounded and has no durable spool, replay, delivery guarantee, or per-run receipt. Outages, overflow, and process crashes can lose spans. The nullable trace ID can still be saved when a particular trace never reaches Phoenix.

The database claim still commits before execution. The trace ID stays in a plain local variable during execution; assigning it to a persistent SQLAlchemy object at that point would trigger transaction autobegin. It is assigned to the row only inside the final save transaction. Thus instrumentation preserves the no-open-transaction boundary during driver calls.

Steps and state snapshots still finalize at the end. Worker/process recovery remains unimplemented. Tracing may expose a partial execution after a crash, but it does not repair its database lifecycle.

## Verification

- Automated tests verify six-span demo hierarchy, shared trace ID and parents, no fake LLM spans, optional model-span nesting, selected attributes, error statuses, and no raw exception events.
- A blocked/throwing test exporter demonstrates that execution can finish before export succeeds or fails.
- A real PostgreSQL integration test links a saved run's trace ID to the in-memory root span and retrieves it through the API.
- Existing concurrent admission/transaction tests continue to pass.
- Browser verification followed a saved run link into Phoenix, inspected the six-span trace, and inspected the rejected-tool diagnostic.
- A real local outage check stopped Phoenix, ran the agent through the API, and retrieved its completed refund result from PostgreSQL while the collector remained unavailable.

## Next learning step

Explain why a trace can be operationally OK while the task is wrong. Then implement one deterministic evaluator comparing the final ledger with the expected refund amount/count. Review that evaluator before introducing fault scenarios or aggregate reliability claims.
