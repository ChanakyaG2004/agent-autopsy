# Durable jobs and background workers

The [release guide](release.md) now covers packaged startup and full acceptance checks. This document explains the worker milestone and its original verification.

Agent and benchmark execution now runs in a separate worker process. HTTP submission saves a job and returns **202 Accepted**; it does not initialize a model provider or wait for inference. Closing the browser does not cancel accepted work. Refreshing or polling reads stored status rather than resubmitting an agent.

## Why PostgreSQL first?

The application already depends on PostgreSQL. Keeping the queue there lets one transaction save a job receipt, reserve its experiment, and—for a benchmark—save its entire schedule. There is no database-plus-broker dual-write gap, Redis service, or extra Python dependency in this milestone.

Workers select a queued row using `FOR UPDATE SKIP LOCKED`. One owns the row; another can take a different unlocked job. PostgreSQL explicitly documents this use for queue-like tables in its [locking-clause reference](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE). Ordering is oldest-first among available rows, not a guarantee of strict global FIFO under contention. Queue acceptance uses a short advisory transaction lock to enforce a capacity of 100 active jobs and serialize concurrent idempotent submissions.

## Request and execution flow

```mermaid
sequenceDiagram
    participant UI as Browser
    participant API as FastAPI
    participant DB as PostgreSQL
    participant W as Worker process
    participant M as Local/model provider
    UI->>UI: Save request UUID before POST
    UI->>API: POST job with request_id
    API->>DB: Atomically save receipt + reservation/schedule
    API-->>UI: 202 + job identity
    W->>DB: Claim unlocked queued job + unique lease token
    W->>DB: Commit running AgentRun before agent starts
    loop Decisions
        W->>DB: Check ownership in a short transaction
        W->>M: Model request outside any DB transaction
        Note over W,DB: Heartbeat renews lease on another connection
    end
    W->>DB: Lock/check ownership; atomically save execution evidence
    W->>DB: Acknowledge processing completion
    UI->>API: GET job and saved results
    API-->>UI: Durable status and independent evaluations
```

`jobs` holds a request ID/hash, kind, frozen payload, execution fingerprint, planned result identity, lifecycle timestamps, claim count, private lease token/expiry, worker identity, and safe error text. A partial unique index reserves one active run job per experiment. Each benchmark owns its precreated experiments and scheduled cells. Run and benchmark execution paths reject work reserved by another job, including attempts through the inline debugging adapter.

The API exposes receipts without the private lease token, request hash, or payload. A run ID is reserved at acceptance; it does not mean an execution row or terminal result already exists.

## State and outcome semantics

| Job state | Meaning |
| --- | --- |
| `queued` | Accepted durably; waiting for ownership |
| `running` | Claimed by a worker with a renewable lease |
| `succeeded` | Processing produced a durable terminal run or benchmark report |
| `failed` | Infrastructure/configuration/source compatibility prevented processing |
| `interrupted` | Started work lost ownership without terminal evidence, or safe recovery limits were exhausted |

Job success is **not** agent success. A completed processing job can contain an agent execution that failed, an incorrect ledger, or a failed grounding check. A fully processed benchmark can contain infrastructure-failed cells. These outcomes remain separate in the UI and summaries.

Agent runs now also support `interrupted`. No evaluation is invented for an unknown execution. Its last saved state may be the initial snapshot; it is labelled **last saved state, final state unknown**, not proof that no mutation occurred. Fault exercise is also unknown after interruption. Such runs cannot be selected automatically as terminal comparisons or qualify for comparison deltas.

## Idempotency and ambiguous responses

The browser saves a UUID and request settings in local storage **before** sending a POST. If the acceptance response is lost, retrying the same settings reuses that UUID. The database returns the original job, even after it finishes. A reused UUID with a different target, driver, kind, or benchmark configuration returns 409. A genuinely new execution requires a new request ID.

Accepted responses clear the pending submission marker; definitive 4xx rejections can also clear it. Network failures, 5xx responses, and malformed acceptance responses retain it. The UI never automatically retries a POST. Reloaded run panels retrieve their saved jobs, and job polling only performs GET requests. A confirmed terminal retry refreshes saved evidence instead of claiming that work still needs to start.

## Leases and fencing

The default lease is 30 seconds, renewed every 10 seconds; supported leases are 15–600 seconds. Lease time uses the database's actual clock, not a worker's host clock or Git timestamps. See PostgreSQL's [current-time functions](https://www.postgresql.org/docs/16/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT).

Ownership requires the job ID, a matching unique token, running status, and an unexpired lease. A protected transaction locks the job row and checks database time after acquiring the lock. This fences result writes against a replacement worker. Heartbeats cannot revive expired tokens. A separate heartbeat connection renews while the main thread waits on model I/O; no execution transaction or database row lock spans a model call.

Ownership is checked before each model decision, before starting a run/cell, and before publishing results. An already in-flight provider request cannot necessarily be cancelled by lease loss or process death. The stale worker cannot publish a terminal result afterward, and its started execution is never automatically replayed. This is conservative duplicate-execution protection, **not exactly-once external side effects**. The refund tools remain in-memory simulations; real payment APIs would additionally require business idempotency keys and reconciliation.

## Crash recovery policy

| Durable evidence after lease expiry | Recovery |
| --- | --- |
| No `AgentRun` exists for the planned identity | Execution never started; safe to reclaim |
| Terminal run saved, job acknowledgement missing | Recover that result and finish the job; do not execute again |
| Running run exists without terminal evidence | Mark run/job interrupted; do not replay the model or tools |
| Benchmark cell has a saved terminal run | Reattach it to its scheduled cell; do not rerun it |
| Benchmark cell started but has unknown outcome | Retain it as an infrastructure failure with an interrupted run |
| Benchmark cell never started | Continue it under fresh ownership |

Recovery is bounded to three worker claims per job. That number counts ownership claims, not model requests, provider retries, or distinct samples. Pending benchmark work is explicitly marked failed if recovery is exhausted, so planned denominators cannot shrink. A saved terminal result can still be recovered without replay at the limit.

Benchmark manifests and stable item/run IDs are created once at acceptance. Recovery resumes that saved schedule rather than rebuilding it from current defaults. Successful or interrupted cells are never repeated. A per-cell infrastructure exception also marks a started run interrupted before the collection finishes; it does not leave a supposedly active execution under a terminal job.

Graceful SIGTERM stops further claims and lets the current bounded job finish. A hard process kill leaves its lease to expire. There is no automatic retry of completed model errors, no cancellation API, and no resume of an interrupted single-agent conversation. Historical inline executions without a job lease are not guessed at or rewritten by queue recovery.

## Source/configuration compatibility

Acceptance fingerprints backend source files, `uv.lock`, `pyproject.toml`, and allowlisted model settings (`OLLAMA_MODEL`, `OLLAMA_BASE_URL`, `OPENAI_MODEL`). Credentials are excluded. Workers capture their fingerprint at startup and refuse new claims after local code/settings change, requiring a restart. A queued job whose fingerprint differs from the worker fails closed before unstarted execution. Benchmark evidence already saved remains intact, and unstarted cells remain in the failure denominator.

This prevents a recovered suite from silently mixing changed runner/evaluator code or selected model settings. It does not freeze mutable provider weights behind a model alias; actual provider/model identity and Ollama weight digests are still measured at execution. Start API and workers from the same checkout and environment, and restart workers after code changes.

## API and local operation

New routes:

- `POST /experiments/{id}/jobs`: `{ "request_id": "<uuid>", "mode": "ollama" }`, returns 202.
- `POST /benchmark-jobs`: `{ "request_id": "<uuid>", "repetitions": 1 }`, returns 202; 1–3 repetitions, scripted suite only.
- `GET /jobs/{id}`: current durable receipt.
- `GET /jobs?experiment_id=<uuid>` or `?kind=benchmark`: bounded listing (`limit` 1–100, nonnegative `offset`).

Start PostgreSQL and apply migration `82ad4f19c532`, then run API and worker in **separate terminals**:

```bash
cd backend
uv run --env-file .env alembic upgrade head
# API terminal
uv run --env-file .env uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
# Worker terminal, also from backend/
uv run --env-file .env python -m app.worker
```

For one queued job and recovery pass:

```bash
uv run --env-file .env python -m app.worker --once
```

Enable worker tracing with `AGENT_AUTOPSY_TRACING_ENABLED=true` and run the local Phoenix collector. A `job.execute` CHAIN span contains the existing `agent.run`, decision, model, tool, and evaluator spans. Job ID and claim count identify the asynchronous work. Queue-wait time comes from receipt timestamps; it is not folded into measured model latency. Trace export remains best effort; PostgreSQL is authoritative for durable outcomes.

The experiments page queues runs and monitors their receipt, then loads saved evidence after processing. `/compare` can queue a nine-cell scripted benchmark and inspect its schedule/results. If no worker is running, jobs remain queued rather than running in a FastAPI background task.

Synchronous HTTP execution routes now return 410 by default. `AGENT_AUTOPSY_SYNC_API_ENABLED=true` explicitly enables the legacy adapter for local debugging. Existing inline engine integration tests opt into it through their fixture; new queue tests use normal production defaults. The explicit benchmark/model-validation CLIs can still execute inline and respect active job reservations. They are not durable worker jobs.

## Files and verification

- `app/jobs.py`: admission, request identity, reservations, leases, recovery, and acknowledgement.
- `app/worker.py`: separate process, heartbeat thread, dispatch, shutdown, and startup compatibility checks.
- `app/job_schemas.py`: request and public receipt contracts.
- `app/execution.py`: shared run path with ownership checks and fenced publication.
- `app/benchmark.py`: atomic schedule preparation and resumable execution of untouched cells.
- `tests/test_jobs.py`: real PostgreSQL races, heartbeats, idempotency, crash boundaries, saved-result recovery, source drift, and count preservation.
- Frontend `jobs.ts`, `job-monitor.tsx`, and `benchmark-queue.tsx`: retained submission identity, runtime guards, safe polling, and queue controls.

Migration adds the queue and interrupted run status without backfilling or regrading historical evidence. Downgrade refuses to delete saved job receipts or invalidate interrupted runs.

### Observed validation

The backend suite passed 343 tests against the dedicated PostgreSQL test database. The frontend passed 13 tests, lint, strict type checking, and a production build. The development database migrated successfully and Alembic reported no schema drift.

Targeted process and browser checks used the development database on October 23, 2026; these are individual observations, not a reliability estimate:

- A queued Ollama run (`1ec6194a-c64f-4f87-ab88-a96ff0f805ed`) was accepted in about 26 ms and completed in a separate worker process. Its ledger, security, and grounding checks passed. Repeating the acceptance request returned the same job.
- Phoenix trace `7c723785d04226c44f9d0bc3240765c9` showed a `job.execute` root with job `581e16d9-1452-4de4-aa62-52ccc85fb6ec`, attempt 1, and nested agent, model, tool, and evaluator spans.
- A test worker was forcibly killed after run `81d4b97e-0f6a-4e90-95b4-6c81cf0e105b` had started. After lease expiry, a replacement worker marked both job and run interrupted. The claim count stayed at 1: it did not replay the model. The UI showed unknown final state, unknown fault outcome, and unavailable evaluations.
- A nine-cell scripted benchmark was queued from `/compare`. Reloading the page retained queued status. Starting the separate worker completed collection `6222c86a` with all nine terminal runs, zero infrastructure failures, and zero pending cells. The claim-only control still failed the ledger checks despite successful job processing.

The full user-led application walkthrough remains deferred. Automated tests and targeted browser/process validation verify this milestone. Next is release packaging: Docker Compose, CI, startup checks, and consolidated documentation.
