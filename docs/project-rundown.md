# Agent Autopsy: first-release rundown

Agent Autopsy is a local reliability lab for agents that take actions. It asks what happened, what the agent actually observed, and whether it handled failure safely. Its first subject is a simulated refund. Claims, state, actions, telemetry, and independent grades remain inspectable together.

Unlike a general RAG tracing project, the difficult boundary here is an uncertain state-changing action. Unlike a general queue project, the durable queue exists to preserve AI execution evidence without replaying unknown actions.

## What was built, step by step

1. **Application boundary:** Next.js typed forms and reusable components; FastAPI validation; PostgreSQL configuration. Saving a draft does not run an agent. Runtime response guards complement TypeScript types.
2. **Persistence:** UUID identities, relational constraints, explicit migrations, bounded listing, and request-scoped sessions make configuration/results survive restarts.
3. **Explicit agent loop:** The driver proposes decisions; the loop validates supported tools, records actions, manages visible history, and stops within a turn limit. Provider code does not own business state.
4. **Phoenix traces:** OpenTelemetry carries parent/child context; OpenInference describes agent, chain, tool, model, and evaluator spans. Saved trace IDs connect diagnostics to application evidence.
5. **Ledger evaluation:** An independent fixed expectation grades actual state. The claim-only negative control ends normally without issuing a refund, proving completion is insufficient evidence of success.
6. **Timeout after commit:** A tool changes state and loses its response. The recovery policy reads the order before another write. Separate ledger and trajectory grades expose why a correct final state does not imply correct recovery.
7. **Permission denial:** Writes fail before mutation. A safe refusal passes policy while leaving the refund goal unmet. Fault selection and actual exercise remain distinct.
8. **Scripted benchmark:** One task, three scenarios, three policies, and frozen schedules/manifests. Every planned cell remains in explicit counts, including infrastructure failures.
9. **Model measurements:** Actual request latency, identity/digest, token coverage, and known subtotals are recorded. Missing usage stays unknown. Ollama supplies real local tool calling without an API key; OpenAI remains optional and mocked in tests.
10. **Saved comparisons:** Original evidence and configuration changes are read without rerunning/regrading. Deltas require compatible task/evaluator/measurement evidence. Two observations do not establish a reliability rate.
11. **Policy and grounded reports:** Unsafe attempts are audited separately from business success. Structured report facts must be supported by agent-visible tool responses; hidden state and unsupported prose cannot silently receive a pass.
12. **Durable execution:** Request IDs prevent duplicate submissions; separate workers renew PostgreSQL leases. Recovery retains completed evidence, continues untouched cells, and marks unknown started runs interrupted without replay.
13. **Release operation:** Non-root application images, ordered migrations, persistent storage, startup checks, optional Phoenix/Ollama, CI, and HTTP acceptance make the repository usable beyond its original development session.
14. **Verification:** Regression suites, a fresh container stack, real model observations, browser checks, and trace inspection cover separate layers. The [verification record](release-verification.md) distinguishes observed from unverified behavior.

## Explain one run end to end

The browser saves a draft and submission UUID, then queues work. FastAPI atomically saves a receipt and target reservation. A worker claims it, saves a running identity, and invokes the bounded loop outside a long database transaction. Tools modify isolated in-memory state and return agent-visible evidence. Independent evaluators grade the result. A final ownership check fences saving it. The UI polls and retrieves saved evidence; Phoenix receives a separate best-effort trace tree.

If the browser disappears, work continues. If Phoenix disappears, authoritative results can still be saved. If a worker disappears after execution starts without terminal evidence, the outcome remains interrupted/unknown. If a result was saved before its acknowledgement was lost, recovery reattaches it without invoking the model again.

## Guided walkthrough

Follow [startup instructions](release.md), then queue the scripted benchmark on `/compare`.

| Case | Lesson |
| --- | --- |
| Normal baseline | Loop completion and a correct ledger can agree |
| Normal claim-only | A final answer does not prove the action occurred |
| Timeout baseline vs recovery | Equal ledger grades can conceal different recovery behavior |
| Permission-denied recovery | Safe refusal can pass policy while failing the business goal |
| Interrupted worker | Last saved state is not proof of final state |
| Saved comparison | Compatibility determines meaningful deltas |
| Phoenix model trace | Model, tool, and evaluator spans answer different questions |

Inspect per-cell evidence, compare timeout policies, reload to verify persistence, and follow trace links. Use the explicit `--model` smoke option for actual Ollama observations. Investigate unsuccessful runs instead of hiding them.

## Understanding checks

- Why does HTTP 202 prove only acceptance, and why reuse a request UUID after a lost response?
- Why should the evaluator use an independent oracle instead of trusting the final answer?
- Why is a retry after a lost response to a write unsafe?
- What does Phoenix explain that PostgreSQL does not, and why is PostgreSQL authoritative?
- How can processing, execution, ledger correctness, recovery, and grounding disagree?
- What does lease fencing protect, and what does it not guarantee for external side effects?
- Why are nine scripted cells not evidence of broad live-model reliability?
- What bottleneck would you measure before adding a broker or Kubernetes?

## Scope and next directions

This completes the agreed first local release when the packaging/verification gates pass. The original learning plan described a much larger future platform. Multi-task repeated model benchmarks, retrieval attacks, calibrated model judges, embedding-based failure clustering, automatic experiment proposals, tenant auth, Kubernetes, and AWS are outside this release.

These are separate future milestones, not hidden startup requirements. A useful research extension adds genuinely distinct tasks and repeated observations before estimating reliability. A useful deployment extension adds authentication, quotas, retention, backups, and business-effect idempotency before public or real-payment integration.

A portfolio description can accurately mention controlled tool faults, explicit agent execution, four deterministic evaluation dimensions, Arize Phoenix traces, durable workers, and tested local containers. Do not claim unbuilt attack coverage, invented reliability improvements, production scale, or cloud deployment.
