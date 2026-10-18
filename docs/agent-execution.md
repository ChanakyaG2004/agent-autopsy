# First agent execution milestone

Current HTTP execution uses [durable jobs and workers](durable-workers.md). This earlier checkpoint documents the shared inline engine; synchronous HTTP routes now require an explicit debugging opt-in.

Historical execution checkpoint. The next branch adds [Phoenix tracing](phoenix-tracing.md) around this same loop; the execution and persistence boundaries described here still apply.

This milestone adds an explicit tool loop for `refund-v1`, with the `normal` scenario only. It establishes the evidence path for later Phoenix tracing and fault experiments. It does not implement those later milestones.

## Interfaces and responsibilities

```text
POST /experiments/{id}/runs
  execution.py: check supported configuration, commit run claim
  agent.py: ask driver, validate/execute tool, feed result back, stop
    DemoDriver                 deterministic script; no model request
    OpenAIDriver               optional Responses API request
    RefundSandbox              isolated, allowlisted business operations
  execution.py: commit final run evidence and experiment status
GET /experiments/{id}/runs
  return bounded persisted history
```

The driver returns a `ModelTurn`: replayable response items, zero or more parsed `ToolCall`s, and an optional final answer. The loop owns control flow; the driver does not directly execute business tools. The sandbox owns business state. The HTTP layer does not implement the loop. A future worker can reuse `execute_agent` without importing FastAPI or SQLAlchemy.

## Concrete normal run

Each execution starts with order `order-123`, paid amount 4900 USD cents, zero refunded cents, and an empty refund ledger. It uses a fresh in-memory sandbox, even when rerunning the same experiment.

1. The driver requests `get_order({"order_id":"order-123"})`.
2. The runner validates the tool name and arguments, then records its returned state.
3. The driver sees that tool output and requests `issue_refund({"order_id":"order-123","amount_cents":4900})`.
4. The tool appends one refund and changes refunded cents to 4900.
5. The driver receives this result and returns a final answer.
6. The runner records the answer, steps, and final state.

The demo follows these steps deterministically. An actual model chooses its own actions and may fail or stop early. The prompt requests an order lookup first; the tool layer itself enforces scope and amount constraints, not the model's full workflow policy.

## Tool boundary

Only `get_order` and `issue_refund` exist. Tool schemas describe expected arguments to the provider. Pydantic validates them again at execution time, with strict types and no extra properties. A string or boolean is not accepted as an integer refund amount. The sandbox refuses unknown orders, nonpositive or oversized amounts, and refunds whose cumulative total exceeds the paid amount. Snapshots are deep copies so later mutations cannot rewrite earlier evidence.

There is no shell tool, live order service, or payment integration. The cumulative refund check is a business guard within a run; it is not a distributed idempotency mechanism. Reruns intentionally use independent simulated orders.

## Bounded loop and failure behavior

At most six model turns execute, with at most one tool call per turn. Multiple calls, unknown tools, invalid arguments, empty model responses, incomplete responses, and provider failures stop the run. A handled failure preserves successful earlier tool actions and the state reached before stopping. Unexpected runner exceptions receive a generic public error.

`completed` means the loop received a final answer. It does **not** mean the refund task succeeded. A test deliberately returns “I refunded everything” without running any tool: execution completes while refunded cents remain zero. This is why automated state-based evaluation is a separate next step.

The OpenAI client uses a 10-second request timeout and disables SDK retries. That timeout is an SDK/network timeout, not a guaranteed end-to-end execution deadline. There is no hard global timer or cancellation protocol. The browser stops waiting after 90 seconds; the server may continue.

## Optional OpenAI adapter

Set `OPENAI_API_KEY` and `OPENAI_MODEL` on the backend, then choose OpenAI in the run panel. Both are required before a run is claimed. The model must support Responses function calling. No model is silently selected, and the selected model label is stored on the run. Live requests can incur charges.

The adapter uses strict function schemas, disables parallel tool calls, and feeds the full output-item sequence back with tool results, following the [official function-calling guide](https://developers.openai.com/api/docs/guides/function-calling). With `store=False`, encrypted reasoning content is requested and replayed in memory for compatible reasoning models; see the [Responses create reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create). Neither raw reasoning items nor credentials are stored in the run's public steps. SDK retry/timeout configuration follows the [official Python reference](https://developers.openai.com/api/reference/python).

The adapter has mocked SDK tests for replay, malformed calls, incomplete responses, and timeouts. No live-model run was performed for this milestone because no backend API key was configured. Demo results must not be described as model quality measurements.

## Database lifecycle

`experiments.status` now accepts `draft`, `running`, `completed`, and `failed`. `agent_runs` has a UUID and a foreign key to its experiment, plus mode, model label, task, status, output/error, JSONB steps, before/after snapshots, and start/finish timestamps. A run row is history; the experiment status summarizes its latest execution.

Transaction 1 validates the saved configuration. Transaction 2 conditionally changes an experiment whose status is not `running` to `running`, inserts the initial run record, and commits. PostgreSQL's conditional update prevents two simultaneous requests from both claiming the same experiment. Model/tool execution happens after this commit, without holding a database transaction open. Transaction 3 saves the outcome and changes both statuses together.

This splits persistence from slow external calls. A real two-connection test blocks the first driver, sees its committed running state from a second connection, verifies that the execution session holds no transaction during driver calls, and confirms the second claim receives 409.

`POST /experiments/{id}/runs` returns 201 for a persisted run, including a run whose execution failed. Missing parent: 404. Unsupported scenario/version or already running: 409. Invalid request: 422. Missing provider configuration: 503 before claim. Database failures: generic 503.

The Alembic revision explicitly replaces the old draft-only constraint; constraint changes were reviewed rather than trusting autogeneration alone. Downgrading refuses to silently relabel executed experiments as drafts.

## Important limits

- Execution is synchronous in a FastAPI request worker thread. There is no job queue, scheduler, crash recovery, cancellation, or admission limit across different experiments.
- The initial running row is durable. Steps and final state are written at the end, including on handled failures. A process crash can lose in-memory partial steps and leave the run marked running. A final database write failure can do the same. Refresh history before retrying; there is no automatic retry.
- Business state is simulated in memory and saved as run snapshots. There are no durable production orders/refunds tables.
- Agent versions are labels; prompt/tool/code hashes and benchmark dataset versions are not tracked yet.
- There is no authentication or deployment hardening. Development services bind to localhost.
- There are no Phoenix spans, latency/token/cost metrics, evaluation scores, fault injections, or version comparisons yet.

## Read the code in this order

1. `app/tools.py`: understand what may change and what is refused.
2. `app/agent.py`: follow one turn through call, execution, feedback, and stopping.
3. `app/providers.py`: see how the same loop accepts a model instead of a script.
4. `app/models.py` and the new migration: inspect the durable evidence contract.
5. `app/execution.py`: identify each transaction boundary.
6. `app/main.py`: map the service to HTTP.
7. `frontend/src/components/experiment-runner.tsx`: trace pending, success, ambiguous error, and history loading states.

## Understanding exercise for the next session

Before adding tracing, write one meaningful deterministic evaluator yourself: given the task and final snapshot, check that exactly 4900 cents were refunded and exactly one refund exists. Then explain why checking the final answer text is weaker. We should review that implementation together before expanding the evaluation system.
