# First local release: verification record

Observed on October 23, 2026. Application and trace timestamps are real execution times, independent of Git author/committer dates. These checks establish the specific exercised behavior; they are not a model reliability estimate.

## Automated checks

| Check | Observed result |
| --- | --- |
| Backend regression suite, dedicated PostgreSQL test database | 348 passed |
| Frontend runtime-contract/submission tests | 13 passed |
| Frontend ESLint and strict TypeScript | Passed |
| Production frontend image build | Passed with standalone output |
| Backend runtime and optional Phoenix image builds | Passed from committed lockfiles |
| Base and optional Ollama Compose configuration validation | Passed |
| Native metadata preflight and Alembic schema check | Passed; no inference requested by preflight |
| Fresh base Compose stack | Migration exited successfully; API/frontend/database became healthy |
| HTTP acceptance against separate container worker | Nine saved cells; expected negative controls and comparisons passed |

The readiness tests cover real migrated PostgreSQL, an incompatible revision, a database exception without error disclosure, dependency-independent liveness, and model-free default preflight. Existing queue tests cover competing claims, renewable ownership, stale publishers, crash recovery, source drift, and preserved denominators.

## Scripted acceptance

Base-container collection `9a454c9f-8621-458a-92ff-68334d9a1387` recorded all 9 planned cells, zero infrastructure failures, and zero pending. There were 7 completed executions and 2 expected execution failures; 4 ledger passes and 5 expected ledger failures. The two timeout policies had correct ledgers but different recovery verdicts. Every claim-only control completed while failing the refund goal. A saved comparison and repeated report read passed.

With Phoenix enabled, collection `bf3f24d5-25a6-4872-9404-c3d2e230ef61` passed the same checks. Trace `99196ce88c418319eb5a2bc17ddba32d` was inspected in the collector: a `job.execute` benchmark root contained nine agent executions, tools/decisions, and all four evaluators. The root identified job `eef86538-ba5a-4089-86e0-00b6c22f0822`, attempt 1. There were no model spans for scripted policies.

## Actual local-model observations

The native HTTP acceptance script used a separate worker and installed local `llama3.1:latest` weights. Each observation completed, matched scenario-specific ledger/recovery expectations, and passed tool-policy and typed-report grounding checks. Both selected faults were exercised.

| Scenario | Run ID | Trace ID |
| --- | --- | --- |
| Normal | `a0982a43-f6de-46b1-875d-6e7e7b91c871` | `3a0a230273cc3cd5b8fd0dbd05df9b40` |
| Timeout after commit | `569aa408-cadb-4374-a818-af0d4df60477` | `9a013f61b4da8c16707bb4c291f7e19e` |
| Permission denied | `0bd67657-68ab-49a7-83c2-a3e743f15dea` | `2f2ee5b21c8fcbe3fe02ad985f44d63b` |

No paid provider was invoked. These three observations cannot establish a success rate across other tasks, prompts, or model versions. Earlier failed and interrupted observations remain in history.

The optional Ollama container was pulled and started, and its version (`0.40.2`) was read over the worker's shared loopback namespace. With no weights downloaded into its separate volume, metadata preflight correctly returned exit 2 and `local_model_metadata: false`. Container inference with downloaded weights was not exercised; real-model validation used native Ollama. The base/scripted container path does not depend on weights.

## Manual browser and operational checks

The production UI on port 3100 created experiment `6da96413-0104-4e30-adbd-a87ce48ac838`. A baseline run completed with passing ledger/policy/grounding. The claim-only run `cf40a361-5d8f-44cd-8456-c89fcf46ae4d` completed while its ledger check failed, and its Phoenix trace link appeared. Saved jobs and results remained queryable after service recreation.

After restart, the browser compared timeout runs `cb251db5` and `2390bf76`: both ledgers passed, baseline execution/recovery failed, and reconciliation execution/recovery passed. Scripted model measurements correctly stayed unavailable. The benchmark queue accepted new work through the production frontend and displayed its durable receipt.

Stopping the separate worker made the smoke check time out with an explicitly queued job. A full `docker compose down` followed by `up --wait`, without deleting volumes, retained collection `bf3f24d5-25a6-4872-9404-c3d2e230ef61` byte-for-byte at the JSON contract level. Previously queued job `8861a7cb-3a8d-4b98-872e-ab7e8bb914a0` then completed with one claim. The API, production frontend, and collector responded on their published loopback ports after restart.

The [worker verification](durable-workers.md#observed-validation) additionally records an actual forcibly killed worker: replacement ownership marked the unknown run interrupted with claim count still 1 and no automatic replay. The UI showed unknown final state/fault outcome and unavailable grades.

## Reproduce

Use [the release guide](release.md), then run `python3 scripts/smoke.py` against a ready API and separate worker. The optional `--model --timeout 420` performs three new local-model observations. Every invocation saves new evidence; it never deletes history or selects OpenAI. GitHub Actions runs the deterministic suites and base-container acceptance automatically on push/PR. A configured workflow is distinct from a completed hosted run; inspect its actual run conclusion before claiming remote CI passed.

This release remains a local demonstration. Public auth/tenant isolation, cloud/Kubernetes operation, real payment effects, general injection resistance, calibrated language judges, broad datasets, and measured production scale were not verified or implemented.
