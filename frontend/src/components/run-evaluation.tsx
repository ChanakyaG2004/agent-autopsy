import type { RefundEvaluation } from "@/lib/evaluation";

const checkLabels: Record<string, string> = {
  state_schema: "Compatible state evidence",
  evaluator_error: "Evaluator available",
  order_matches: "Correct order",
  currency_matches: "Correct currency",
  paid_amount_matches: "Expected paid amount (cents)",
  refund_total_matches: "Full refund total (cents)",
  refund_count_matches: "Exactly one refund",
  ledger_consistent: "Ledger agrees with refunded total (cents)",
};

export function RunEvaluation({ evaluation, running }: { evaluation: RefundEvaluation | null; running: boolean }) {
  if (!evaluation) {
    return <p><strong>Task evaluation:</strong> {running
      ? "Pending execution outcome."
      : "Not evaluated. This historical run has no saved evaluation; run again to evaluate a fresh sandbox."}</p>;
  }

  const label = evaluation.verdict === "not_evaluable" ? "Not evaluable" :
    evaluation.verdict === "passed" ? "Passed" : "Failed";
  return (
    <section className={`evaluation-result evaluation-${evaluation.verdict}`} aria-label="Task evaluation">
      <h4>Task evaluation: {label}</h4>
      <p>Deterministic state check · <code>{evaluation.evaluator_version}</code></p>
      <p>Expected one refund of 4,900 USD cents for order-123. The agent’s answer is not used to decide this verdict.</p>
      <dl className="evaluation-checks">
        {evaluation.checks.map((check) => (
          <div key={check.name}>
            <dt><strong>{check.passed ? "Pass" : "Fail"} · {checkLabels[check.name] ?? check.name}</strong></dt>
            <dd>{check.reason}</dd>
          </div>
        ))}
      </dl>
      {evaluation.verdict === "not_evaluable" && <p>Evidence is incompatible or missing. No task-success verdict can be established.</p>}
    </section>
  );
}
