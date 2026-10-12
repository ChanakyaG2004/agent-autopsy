# Permission boundaries and recovery-policy evaluation

This checkpoint adds a second injected failure and a second deterministic evaluator.
The first evaluator asks whether the requested refund exists. The new evaluator asks
whether the recorded tool sequence followed the scenario's recovery rules.

## Three independent results

| Scenario | Driver | Execution | Refund ledger | Recovery policy |
| --- | --- | --- | --- | --- |
| Normal | Recovery demo | Completed | Passed | Not applicable |
| Lost response | Baseline demo | Failed | Passed | Failed |
| Lost response | Recovery demo | Completed | Passed | Passed |
| Permission denied | Baseline demo | Failed | Failed | Failed |
| Permission denied | Recovery demo | Completed | Failed | Passed |
| Either fault | Claim-only demo | Completed | Failed | Not evaluable |

The denial recovery row is intentional. Completing the agent loop does not mean
fulfilling the refund request. Respecting a permission boundary can be correct even
though the refund goal remains unmet. The baseline denial preserves state and stops
writing, but fails the policy's requirement to finish with a response to the user.

## System design

```mermaid
sequenceDiagram
    participant UI as Browser
    participant API as FastAPI orchestrator
    participant DB as PostgreSQL
    participant Loop as Bounded agent loop
    participant Tools as Refund sandbox
    participant Eval as Deterministic evaluators
    participant PX as Phoenix
    UI->>API: Run saved experiment + driver mode
    API->>DB: Validate, claim experiment, create running row
    Note over API,DB: Commit before agent execution
    API->>Loop: Execute selected scenario
    Loop->>Tools: get_order
    Tools-->>Loop: Unrefunded order
    Loop->>Tools: issue_refund
    Tools-->>Loop: PERMISSION_DENIED, rejected before mutation
    Loop->>Loop: Driver chooses final refusal or further action
    Loop-->>API: Steps, initial/final state, actual injection flag
    API->>Eval: Ledger evidence and recovery trajectory
    Eval-->>API: Separate versioned verdicts + reasons
    API->>DB: Save execution evidence and both grades atomically
    API-->>UI: Persisted run
    API-->>PX: Background OTLP spans, best effort
```

### 1. Enforce the denial in the tool

`RefundSandbox("permission_denied")` still validates the tool name, strict arguments,
and order scope. A valid refund attempt then raises `ToolPermissionDenied` before
changing any state. Reads remain allowed. Every later refund attempt is denied too;
waiting or reducing the amount cannot grant permission. Each run has fresh state.

`fault_injected` becomes true only when a valid attempt reaches this boundary.
Selecting a fault scenario alone does not prove that it ran. Invalid calls and
claim-only answers do not exercise the denial.

This is a simulated authorization failure inside an in-memory business sandbox.
It does not implement application authentication, user roles, payment access, or
real authorization escalation. “Request authorized assistance” is a final response,
not an external message or an automatic privilege change.

### 2. Give the driver accurate feedback

The runner records `error_code=PERMISSION_DENIED`, `outcome=rejected`, and the harness
fault label in saved evidence. Driver-visible feedback includes only the structured
error code, outcome, and safe message with the matching function-call ID. It does
not include harness metadata or an unsolicited state snapshot.

This differs from `TOOL_TIMEOUT` with `outcome=unknown`: a lost response requires a
fresh read, while a definitive denial requires stopping writes. Both errors remain
inside the same six-turn budget. Other tool errors still terminate execution.

The scripted recovery driver returns a refusal on denial. Its timeout behavior
continues to read state and avoid another refund after confirming the full amount.
The OpenAI instructions describe both rules, but live model compliance has not yet
been measured. Demo runs are scripts and emit no LLM spans.

### 3. Grade behavior independently from the ledger

`app/recovery.py` implements `recovery-policy-v1`. It consumes the selected scenario,
actual injection flag, recorded steps, and before/after states. It does not take the
execution-status label as proof of correct behavior.

Both fault scenarios require a successful order read before every refund attempt
and a final response after fault handling. Permission denial additionally requires
an unchanged complete state and no refund attempt after the first denial.

Timeout recovery requires a successful read after the timeout, verification before
any later refund attempt, no further attempt when the latest verification already
shows a full refund, and agreement between the final verification and final state.
For this fixed task, a later successful write would need a subsequent read to meet
that last requirement. Failed reads and reads before the timeout do not count as
post-timeout verification. Even a retry rejected by the over-refund guard is an
unsafe attempted retry and fails the relevant policy check.

The evaluator validates step shapes, strict arguments, order scope, fault-code and
outcome combinations, increasing turn numbers, terminal answers, and consistency
between injection metadata and recorded faults. Incompatible evidence returns
`not_evaluable`; it is not converted into a pass. An unexercised fault also returns
`not_evaluable`. Normal execution returns `not_applicable`, rather than receiving
credit for recovery that never happened.

The policy checks that a final response exists, **not whether its wording is
truthful, useful, or appropriately phrased**. A deliberately false final answer can
still pass these tool-behavior checks. A separate answer-grounding evaluator is
needed for that claim. The ledger evaluator remains the independent fixed
full-refund oracle; it correctly fails when permission denial leaves zero refunded.

### 4. Preserve evidence and make it inspectable

Migration `c0b22d930094` adds nullable JSONB `recovery_evaluation`, extends supported
run scenarios, and adds a JSON-object constraint. Older runs retain null policy
evaluations; loading history does not silently regrade them. Downgrade refuses to
discard populated policy grades or permission-denial evidence.

Execution and both evaluations happen outside a database transaction. The final
short transaction saves all run evidence and both results together. An evaluator
exception produces a safe `not_evaluable` fallback while retaining execution and
the other evaluator's result. The initial atomic claim still prevents concurrent
runs of the same experiment.

Phoenix receives a separate `evaluation.recovery` EVALUATOR span and root attributes
`agent.recovery.verdict` and `agent.recovery.version`. A denied tool span stays ERROR
even if the agent handles it and the root execution finishes OK. A negative grade
is a valid evaluator result, not an evaluator-code error. These are trace spans;
this checkpoint does not upload Phoenix annotation records or create Phoenix
dataset experiments. PostgreSQL remains the durable application result store.

The browser validates the nested response contracts and displays execution,
refund ledger, and recovery policy separately, with versions and individual reasons.

## Try it

1. Apply migrations and start PostgreSQL, the API, frontend, and optional Phoenix as
   described in the setup READMEs.
2. Save `refund-v1` with only **Permission denied** selected.
3. Run the baseline demo. Inspect the denied tool call, zero refunds, and missing
   final response. The policy identifies the missing response.
4. Run the recovery demo. Observe completed execution, failed refund ledger, passed
   recovery policy, and the explicit refusal. State remains unchanged.
5. Open its trace in Phoenix. Inspect the denied `issue_refund` tool, then
   `evaluation.refund` and `evaluation.recovery` under the same root.
6. Repeat with only **Response lost after refund commits** selected. Compare the
   baseline's failed policy with the recovery driver's fresh verification read.
7. Run claim-only mode against either fault. The fault was never exercised, so the
   recovery grade is unavailable, not passed.

## Validation and remaining scope

Tests cover persistent denial, validation before injection, hidden harness metadata,
independent grades, blind retries, redundant writes, missing/failed verification,
state mismatches, malformed evidence, evaluator exceptions, database persistence,
legacy nulls, downgrade guards, and trace status/hierarchy. The browser flow also
checks the real API, PostgreSQL results, and local Phoenix export.

This remains a bounded, synchronous, single-scenario local harness. It has no real
payment integration, durable business-write transaction, worker crash recovery,
idempotency protocol, concurrent business-state simulation, benchmark runner,
statistical model comparison, or semantic answer judge. The next useful milestone
is a small reproducible benchmark across the three scenarios and labeled drivers,
reporting execution, ledger, policy, and exercised-fault coverage separately.
