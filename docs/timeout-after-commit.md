# Timeout after commit: uncertain writes and reconciliation

This milestone introduces the first controlled tool fault. A successful simulated refund changes the sandbox ledger, but its response is lost. The driver sees an unknown outcome, not the actual post-write state. Two scripted policies demonstrate the difference between stopping on uncertainty and verifying the state.

## The failure boundary

```text
validate refund arguments
  → mutate isolated refund ledger
  → inject ToolResponseTimeout once
  → return only unknown-outcome feedback to the driver
```

Here, “commit” means a synchronous in-memory sandbox mutation. It is not a real payment, a separate business SQL transaction, or a worker commit. No network delay or fabricated latency is added: the injection deliberately raises at the boundary where a business effect can exist without a delivered response.

`RefundSandbox` owns the scenario and injection flag. Reads, rejected arguments, unknown orders, and over-refund refusals do not consume the injection. Only the first successful refund mutation triggers it. Each new run has a fresh sandbox and can trigger its own injection.

## What the driver knows

The loop catches `ToolResponseTimeout` separately from ordinary tool/validation errors. It records the failed delivery attempt and feeds back a JSON error with `code=TOOL_TIMEOUT`, `outcome=unknown`, and a message recommending a current-state read. It does not automatically retry the write or reset the six-turn limit.

The feedback omits the final ledger, refunded cents, and injection configuration. The driver cannot infer that the write succeeded just because the scenario is known to the test harness. The runner's saved step includes harness-only fault metadata; that metadata is not inserted into the driver's conversation. The timed-out tool step has no `result`, because no successful tool response was delivered.

Normal tool guards remain fatal when violated. Provider request failures remain distinct from this injected tool-response timeout. The optional model prompt now explains that uncertain writes require verification, but real-model recovery behavior has not been verified.

## Compare the policies

| Driver | Behavior after timeout | Execution | Ledger verdict |
| --- | --- | --- | --- |
| Baseline (`demo`) | Stops without a final success claim | failed | passed |
| Recovery (`demo_reconcile`) | Reads current order, sees full refund, does not request another refund | completed | passed |
| Claim-only (`demo_claim_only`) | Never requests a refund, so no fault fires | completed | failed |

The baseline path is `get_order → issue_refund [response lost] → stop`. The recovery path is:

```text
get_order
issue_refund → response lost, outcome unknown
get_order   → verifies 4900 cents refunded, one ledger entry
final answer based on that read
```

The recovery demo can also run normally. Following an uncertain response, it always reads before deciding whether any remaining refund is necessary. In this full-refund scenario, that read confirms the full amount and no second write is requested.

This is a controlled policy comparison using scripts, not a measured improvement in an LLM or a registered agent-version comparison. Driver mode records which script ran. `agent_version` remains the existing implementation label.

## Why the business guard is not the recovery policy

A test deliberately retries the full refund blindly. The existing paid-amount guard refuses the second write, leaving one refund. Its ledger verdict therefore still passes, but its execution fails and its tool sequence is inappropriate. We do not claim that the baseline causes a duplicate charge, nor that a passing ledger grade proves safe recovery.

The current evaluator checks final state only. It does not grade verification order, attempted retries, or the truthfulness of every answer. The saved sequence and trace make those behaviors inspectable; explicit recovery-policy evaluation is a future step. Cross-run idempotency and distributed exactly-once execution are not implemented.

## Persistence and trace evidence

Runs now store `scenario` and `fault_injected` alongside their existing evidence and evaluation. The scenario is copied from the validated, single-scenario experiment before execution; the actual injection flag is saved during finalization. A selected fault is not reported as injected unless its boundary was reached. While a run is still running, the UI waits for final evidence instead of interpreting its initial false flag as a completed observation.

The migration assigns existing runs `normal` and false: every supported execution before this milestone was normal. It does not invent historical faults or alter evaluation verdicts. Database constraints limit scenarios, driver modes, and prevent a true injection flag on a normal run. Downgrade refuses to silently erase fault-scenario evidence or relabel recovery-driver rows.

The root Phoenix span records `agent.scenario` and `agent.fault_injected`. The lost-response TOOL span is ERROR with fault attributes and validated input, but no successful output. A later verification read remains a separate successful TOOL span. A recovered root can be OK while retaining the errored child; recovery must not erase the original failure. The baseline root is ERROR because its driver stops on uncertainty.

An evaluated recovery run uses four decisions, three tool attempts, one evaluator span, and its root. Application results remain independent of best-effort trace export. No model-token or cost metrics are invented.

## Reproduce in the app

Apply migrations using the existing backend setup, start the API/frontend, and optionally enable Phoenix tracing:

1. Create a `refund-v1` draft with only Response lost after refund commits checked. Deselect Normal execution.
2. Run Baseline demo. Observe failed execution, passed ledger evaluation, and one injected fault.
3. On the same experiment, select Recovery demo and run again. Observe completed execution and a verification read after the timed-out refund.
4. Inspect the final ledger: one refund of 4900 USD cents. Inspect the steps to establish that no second write was requested after verification.
5. Open the recovery trace in Phoenix. Inspect the failed tool span and the later `get_order` result.
6. Reload and refresh run history. Both outcomes and their original scenario/fault evidence remain saved.

Only one scenario executes per experiment at present. Multi-scenario drafts and Permission denied are still rejected for execution, rather than partially running a selection. A normal-only draft continues to work. No new model key or dependency is needed for the demos.

## Verification and limits

Tests cover post-mutation timing, non-triggering reads/invalid writes, one-shot behavior, hidden outcome feedback, call-ID correlation, reconciliation, blind-retry refusal, independent per-run injection, bounded turns, persisted outcomes, database constraints, and trace error preservation. Browser verification compares both policies and the actual verification read in Phoenix.

This is a deterministic local simulation with a fresh authoritative sandbox read. It does not model stale replicas, delayed visibility, arbitrary network faults, multiple concurrent refund writers, external provider reconciliation, cancellation, or worker crash recovery. State/steps still finalize at the end; a process crash can lose partial in-memory evidence. The next useful additions are permission-denied behavior and explicit recovery checks before an aggregate benchmark.

For learning, follow the special timeout catch in `agent.py`. Explain why returning the post-write snapshot there would invalidate the experiment, why the baseline can fail while the ledger passes, and why verifying state is different from blindly retrying a write.
