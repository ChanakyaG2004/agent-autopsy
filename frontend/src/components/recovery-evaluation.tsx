import type { RecoveryEvaluation } from "@/lib/recovery";

const labels: Record<string, string> = {
  read_before_write: "Read before writing",
  final_response: "Final response recorded",
  state_unchanged: "Denial leaves state unchanged",
  no_write_after_denial: "No retry after denial",
  read_after_timeout: "Fresh read after timeout",
  verify_before_retry: "Verify before retrying",
  no_redundant_refund: "No redundant refund attempt",
  verification_matches_final: "Verification agrees with final state",
  fault_not_exercised: "Fault was not exercised",
  evidence_schema: "Compatible recovery evidence",
  evaluator_error: "Evaluator available",
  fault_scenario: "Recovery scenario",
};

export function RecoveryPolicy({ evaluation, running }: {
  evaluation: RecoveryEvaluation | null; running: boolean;
}) {
  if (!evaluation) return <p><strong>Recovery policy:</strong> {running ? "Pending execution outcome."
    : "Not evaluated for this historical run. Run again to evaluate fresh evidence."}</p>;
  const label = { passed: "Passed", failed: "Failed", not_evaluable: "Not evaluable",
    not_applicable: "Not applicable" }[evaluation.verdict];
  return (
    <section className={`evaluation-result evaluation-${evaluation.verdict}`} aria-label="Recovery policy evaluation">
      <h4>Recovery policy: {label}</h4>
      <p>Deterministic trajectory checks · <code>{evaluation.evaluator_version}</code></p>
      <p>Checks recorded tool behavior and state. Final-response wording and model quality are not graded.</p>
      <dl className="evaluation-checks">
        {evaluation.checks.map((check) => <div key={check.name}>
          <dt><strong>{evaluation.verdict === "not_applicable" ? "N/A" : check.passed ? "Pass" : "Fail"} · {labels[check.name] ?? check.name}</strong></dt>
          <dd>{check.reason}</dd>
        </div>)}
      </dl>
    </section>
  );
}
