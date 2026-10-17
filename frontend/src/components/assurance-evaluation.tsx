import type { GroundingEvaluation, SecurityEvaluation } from "@/lib/assurance";

export function AssuranceEvaluation({ security, grounding, running }: {
  security: SecurityEvaluation | null; grounding: GroundingEvaluation | null; running: boolean;
}) {
  return <>
    {([{ title: "Tool-policy audit", grade: security, description: "Audits requested tools, argument scope, reads, retries, and bounded state. Unsafe attempts can fail even when tools blocked them. This is not a general security guarantee." },
      { title: "Typed-report grounding", grade: grounding, description: "Checks the structured refund report against the latest agent-visible tool response. Free-form answers and general language quality are not graded." }]).map(({ title, grade, description }) =>
      <section key={title} className={`evaluation-result evaluation-${grade?.verdict ?? "unknown"}`} aria-label={title}>
        <h4>{title}: {grade?.verdict.replaceAll("_", " ") ?? (running ? "Pending" : "Not evaluated for this historical run")}</h4>
        <p>{description}</p>
        {grade && <><p><code>{grade.evaluator_version}</code></p><dl className="evaluation-checks">{grade.checks.map(check => <div key={check.name}>
          <dt><strong>{grade.verdict === "not_evaluable" ? "Unavailable" : check.passed ? "Pass" : "Fail"} · {check.name.replaceAll("_", " ")}</strong></dt>
          <dd>{check.reason}</dd>
        </div>)}</dl></>}
      </section>)}
    {grounding?.claim && <p className="grounded-claim"><strong>Reported outcome:</strong> {grounding.claim.outcome === "state"
      ? `${grounding.claim.refunded_cents} USD cents across ${grounding.claim.refund_count} refunds`
      : grounding.claim.outcome === "denied" ? "Permission denied; no ledger counts asserted" : "Write outcome unknown; no ledger counts asserted"}
      {" · "}{grounding.claim.order_id} · cites tool turn {grounding.claim.evidence_turn}. This is the agent’s claim; see the grounding verdict above.</p>}
  </>;
}
