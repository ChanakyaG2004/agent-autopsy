# Comparing recorded execution evidence

Open **Compare saved runs and policies** on the experiments page, or visit `http://127.0.0.1:3000/compare`. Start PostgreSQL and FastAPI as usual. Phoenix is optional for reading results, but must be running to follow a local trace link.

This milestone adds two views: a pair of recorded runs and a saved scripted benchmark. Loading, selecting, comparing, and refreshing only read stored evidence. They never execute an agent, call a model, or regrade a historical result. There is no schema migration or new frontend dependency.

## Why two views?

A run pair answers: **what differed in these two observations?** A benchmark table answers: **what happened across this saved suite's scheduled cells?** Mixing the two would imply that scripted controls measured a live model. The product keeps them separate and presents raw counts instead of a combined reliability score.

Execution completed means the loop returned a final answer. It does not mean a refund occurred. Ledger correctness checks the business result; recovery policy checks the action sequence. A safe refusal after permission denial can pass policy while leaving the refund goal unmet.

## Request flow and system design

```mermaid
sequenceDiagram
    participant UI as Comparison page
    participant API as FastAPI
    participant DB as PostgreSQL
    UI->>API: GET /runs?limit=100
    API->>DB: Join saved runs to experiments
    API-->>UI: Run choices and labels
    UI->>API: GET /run-comparisons?baseline_id=…&candidate_id=…
    API->>DB: Read both saved runs and experiments
    API->>API: Check eligibility; compute allowed deltas
    API-->>UI: Evidence, checks, changes, measurements
    Note over UI,DB: No execution or evaluation is triggered
```

The page is a Next.js Server Component. Its panels use Client Components for selection, fetch state, and refresh. Typed runtime guards reject malformed responses. Read requests have a ten-second wait limit and refreshable errors. Changing a selection cancels the old browser request and hides the old report.

`backend/app/comparisons.py` owns the rules. The response is versioned as `recorded-runs-v1`. Evidence stays in existing run records; the UI presents stored grades and the API's flags and deltas. The initial selection prefers a terminal model pair with matching driver, scenario, and task-contract label, then a matching scripted pair, then any two terminal runs. This is a convenience; the server checks actual comparability. The browser lists the latest 100 runs. The API supports `limit` 1–100 and nonnegative `offset`.

## Comparison eligibility

| Measurement | Required evidence |
| --- | --- |
| Ledger verdicts | Same task text, task-contract label, scenario, starting state, terminal executions, and available ledger grades with matching evaluator version and expectation |
| Recovery verdicts | Matching case, available policy grades with matching evaluator version, and actual fault exercise on both sides |
| Request count and time delta | Matching terminal case and recorded model requests on both sides |
| Core token deltas | Matching terminal case, complete usage, same provider and one matching reported model identity; Ollama also requires matching nonempty weight digests |

Normal runs are not recovery tests. An unexercised selected fault cannot establish recovery behavior. Missing grades stay unavailable. Scripted runs have no model measurements.

Raw observations stay visible when a delta is suppressed. Partial token usage stays labelled partial. A dash means unavailable, not zero; an actual zero remains zero. Token differences across model identities are suppressed because tokenization can differ. Client request durations include every attempt, model loading, and caching. They are not a controlled performance comparison.

Configuration changes include driver, provider, model label, task-contract label, scenario, telemetry version, and stored request settings such as prompt/tool hashes and model digest. `agent_version` currently identifies the supported task contract (`refund-v1`), not a unique code release. A changed prompt fingerprint identifies a change but cannot recover the prior prompt text. Per-run full source snapshots and repeated live-model suites remain future work; benchmark collections retain their source manifest.

Both sides have expandable evidence: full run ID, actual observation time, agent claim, ledger/policy checks, executed steps, before/after state, model measurements, and a Phoenix trace link when recorded. No semantic answer judge or dollar-cost estimate is introduced.

## Concrete local-model example

The existing normal-scenario Ollama pair illustrates the distinction:

| Recorded fact | Earlier `984d34cb…` | Candidate `7b51fb77…` |
| --- | --- | --- |
| Execution | Completed | Completed |
| Refund ledger | Failed | Passed |
| Tool behavior | Read, then answered without executing the refund | Read, issued refund, then answered |
| Model requests | 2 | 3 |
| Complete total tokens | 771 | 1,330 |
| Recovery | Not applicable | Not applicable |

Both used the same installed `llama3.1:latest` weights. The recorded configuration difference is the instruction hash: the candidate clarified native tool calling. The actual observations were made October 19, 2026. These are local database records, not repository fixtures, so another clone starts without them.

The pair shows an observed correction and increased token use. It does **not** establish a reliability improvement, latency speedup, or causal effect from one sample. The earlier failure remains intact. No new live-model call was needed to build this view.

## Scripted policy benchmark

The lower panel reads `GET /benchmarks?limit=20` and `GET /benchmarks/{id}`. It uses the saved `benchmark-counts-v1` summary, not recalculated grades. The policy table shows recorded/planned work, execution completion, ledger counts, four recovery verdict counts, exercised/selected faults, infrastructure failures, and pending work. Inspect individual cells for evidence and traces, or expand the reproducibility manifest.

`refund-resilience-v1` has **one distinct task**, three scenarios, and three scripted drivers. One repetition creates nine cells. Repetitions do not increase task diversity. To collect a suite in an empty database:

```bash
cd backend
uv run --env-file .env python -m app.benchmark --repetitions 1
```

Refresh afterward. The local validation collection recorded 9 runs: 7 executions completed, 4 correct ledgers, 2 recovery passes, 2 recovery failures, 2 unavailable recovery grades, 3 normal cases, and 4/6 selected faults exercised. The claim-only control never reaches the write that triggers a fault. Completed collection does not mean all results passed.

## Verification and limits

All 273 backend tests pass, including signed/zero deltas, mismatched tasks/scenarios/states/contracts, incomplete usage, missing/changed model identity, unavailable grades, fault coverage, pagination, and read-only behavior. Five frontend contract tests cover selection, malformed responses, unavailable measurements, and count partitions that cannot drop failed work. Lint, strict types, and production build pass. Targeted browser checks cover the saved local-model pair, mismatched-case suppression, and scripted table/cell traces; the full application walkthrough remains deferred.

This feature does not add repeated live-model benchmarks, confidence intervals, answer grading, background execution, authentication, or deployment packaging. Next is security and answer grounding, then durable background workers and release packaging.
