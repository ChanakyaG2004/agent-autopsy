# Deterministic refund evaluation

The platform now answers a concrete question from saved business evidence: did this isolated sandbox end with exactly one full refund for the expected order? Every new normal-scenario run gets an evaluation alongside its execution outcome. No model judge or provider key is required.

## Why execution status is insufficient

An agent can return a final answer without taking an action. Conversely, a refund can succeed before a later driver request fails. We therefore retain two independent fields:

| Case | Execution status | Ledger verdict |
| --- | --- | --- |
| Normal demo reads and refunds correctly | completed | passed |
| Claim-only demo says it refunded but skips tools | completed | failed |
| Driver fails after the correct refund | failed | passed |
| Evidence is missing/incompatible, or evaluator cannot finish | independent of verdict | not_evaluable |

The experiment's status still summarizes execution. It does not turn into a task-success score. The UI displays the run's task verdict separately, with check-level explanations.

## The oracle and its inputs

`app/evaluation.py` defines `evaluate_refund(final_state)`. Its only input is the final state snapshot. It does not receive final answer text, execution status, model identity, or trace status. This makes it impossible for a persuasive success claim alone to pass the check.

The fixed expectation is independent of the potentially incorrect observed state:

```text
order_id         order-123
currency         USD
paid_cents       4900
refunded_cents   4900
refund_count     1
```

This oracle is specifically for the existing `refund-v1` normal task and its fresh $49 sandbox. We do not infer what should have happened from what the agent did. For example, changing both the paid and refunded amounts to 9800 does not redefine the expected amount to 9800.

## Evidence validation and checks

A strict Pydantic evidence schema requires the known state shape, integer nonnegative totals, and refund entries with an identifier and positive integer amount. Strings and booleans are not accepted as integer cents. Missing fields, incompatible shapes, and extra state fields produce `not_evaluable` with a safe explanation; they are not silently coerced or treated as a successful task.

For compatible evidence, six named checks run:

| Check | What it establishes |
| --- | --- |
| order_matches | Snapshot identifies the expected order |
| currency_matches | Snapshot uses USD |
| paid_amount_matches | The sandbox's paid amount is the expected 4900 cents |
| refund_total_matches | Reported refunded total equals 4900 cents |
| refund_count_matches | Exactly one refund entry exists |
| ledger_consistent | Sum of ledger entry amounts equals the reported refunded total |

All six must pass. Two refunds of 2450 cents each fail the count check even though their sum is correct. A state claiming 4900 refunded cents with an empty ledger fails the count and consistency checks. An empty but internally consistent ledger passes consistency while failing the expected amount/count. Internal consistency alone is insufficient.

Each check stores its name, boolean result, and expected-versus-observed reason. The evaluation also stores the fixed expectation, an observed summary, the overall verdict, and `evaluator_version=refund-ledger-v1`. The function is deterministic and does not mutate its input.

## Execution and persistence flow

```text
commit running claim
  → execute bounded agent loop
  → evaluate final state in memory
  → record evaluation trace span/attributes
  → commit execution outcome + evidence + evaluation together
```

The evaluator runs outside the database transaction, preserving the existing short-transaction design. `agent_runs.evaluation` is nullable JSONB. The database checks that a non-null value is an object; typed application models validate its detailed contract. One column is sufficient while there is one evaluator per run. Multiple evaluators, independently rerun evaluations, or richer version histories could justify a separate evaluations table later.

The HTTP response and subsequent run-history GETs include the same typed evaluation. There is no additional grading endpoint, automatic historical backfill, or silent regrading. Old rows retain null and display Not evaluated. A fresh execution creates new evidence and a new verdict under the current evaluator version.

If the evaluator unexpectedly raises, the service preserves execution and state evidence, records a safe `not_evaluable` result, and logs the exception class. The evaluator span is ERROR. Its private exception payload is not copied into the saved verdict. A database finalization failure still has the existing transaction/failure limitations; this milestone does not add worker recovery.

## Reproduce both outcomes

Use the existing PostgreSQL/API/frontend setup and apply `uv run --env-file .env alembic upgrade head` from `backend/`. No new dependencies are required.

1. Save a `refund-v1` experiment with only Normal execution selected.
2. Choose Deterministic demo, then Run simulated refund. Expect completed execution and a passed ledger verdict.
3. Choose Claim-only demo — intentionally skips tools, then run again. Expect completed execution, a failed ledger verdict, and zero refunds in the final snapshot.
4. Inspect the failed amount/count checks beside the agent's unsupported claim.
5. Reload, reopen the run panel, and refresh history. Both records and their original verdicts remain available.

The claim-only mode is persisted as `demo_claim_only`. It is explicitly a scripted negative control, not a measured LLM failure, an injected network fault, or another agent version. It uses the same runner, sandbox, evaluator, and persistence flow as other supported runs, and makes no model calls.

## Phoenix integration

With tracing enabled, each evaluated run adds `evaluation.refund` with OpenInference kind EVALUATOR, its version, and a JSON output containing the verdict and named boolean checks. The root span carries `agent.evaluation.verdict` and `agent.evaluation.version` for correlation. The normal demo now has seven spans; the claim-only demo has a root, one decision, and one evaluator span.

A failed task verdict is not an instrumentation exception. A completed claim-only run and its successful evaluator execution remain operationally OK, while the evaluator output clearly says `failed`. A driver or tool execution error still marks its operational spans ERROR. An evaluator implementation error marks the evaluator span ERROR and saves `not_evaluable`.

These are trace spans and attributes, not Phoenix annotation API writes, managed evaluator configurations, or dataset experiment results. PostgreSQL remains the durable source for the saved verdict. Collector outages retain the existing best-effort export behavior and do not gate evaluation or saving.

## Scope and trust limits

- A passed ledger verdict establishes these six conditions in one simulated final snapshot. It does not establish response quality, truthfulness, authorization, absence of prompt injection, or success across all parts of a real-world task.
- The evaluator ignores answer text entirely. It exposes disagreement for inspection but does not automatically classify natural-language claims as hallucinations.
- The sandbox is the source of business evidence in this prototype. We have not independently reconciled an external payment provider or production order database.
- Exactly one ledger entry within this fresh sandbox is not a distributed exactly-once guarantee or an idempotency mechanism across runs.
- A correct final state does not establish the entire action trajectory or prove that transient bad actions never occurred. Tool-policy and recovery checks will be separate evaluators as those behaviors are introduced.
- This is one fixed task, not a benchmark dataset. No aggregate success rate, model accuracy, or reliability improvement is claimed. Live OpenAI runs remain unverified.

## Verification and learning

Tests cover correct refunds, skipped refunds, partial/duplicate/excessive refunds, wrong order/currency/paid amount, inconsistent ledgers, malformed evidence, deterministic behavior, and input immutability. PostgreSQL tests verify durable verdicts, null historical evaluations, the negative-control mode, independent status/verdict combinations, evaluator-error isolation, and trace correlation. The browser reproduced passing and failing outcomes, loaded both after reload, and showed the failed verdict in a Phoenix evaluator span while execution remained OK.

Read the comparisons in `evaluate_refund`, then follow one check from its pure result through `execution.py`, the API response, the frontend response guard, and `RunEvaluation`. Explain why two half-sized refunds fail and why a driver error after a successful refund can leave a passed ledger verdict. Next we can introduce controlled tool failures and evaluate recovery against actual state.
