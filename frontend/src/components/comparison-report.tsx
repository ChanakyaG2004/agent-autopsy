import { AssuranceEvaluation } from "./assurance-evaluation";
import { RunEvaluation } from "./run-evaluation";
import { RecoveryPolicy } from "./recovery-evaluation";
import type { ComparisonSide, RunComparison } from "@/lib/comparisons";
import { phoenixTraceUrl } from "@/lib/runs";

const readable = (value: string | null | undefined) => value?.replaceAll("_", " ") ?? "Not evaluated";
export function Verdict({ value }: { value: string | null | undefined }) {
  return <span className={`verdict-pill verdict-${value ?? "unknown"}`}>{readable(value)}</span>;
}
const number = (value: number | null) => value === null ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
const fields: Record<string, string> = {
  request_time: "Model request time (ms)", model_requests: "Model requests", input_tokens: "Known input tokens",
  output_tokens: "Known output tokens", total_tokens: "Known total tokens",
};

function Evidence({ side, label }: { side: ComparisonSide; label: string }) {
  const run = side.run;
  return <details className="comparison-evidence">
    <summary>{label} evidence and trace</summary>
    <p>{side.experiment_name} · {side.agent_version} · {run.mode}</p>
    <p><code>{run.id}</code> · {new Date(run.started_at).toLocaleString()}</p>
    {run.trace_id ? <p><a href={phoenixTraceUrl(run.trace_id)} target="_blank" rel="noopener noreferrer">Open {label.toLowerCase()} trace in Phoenix</a></p>
      : <p>No trace ID was recorded.</p>}
    <p><strong>Task:</strong> {run.task}</p>
    <p><strong>Agent’s claim:</strong> {run.output ?? "No final answer recorded."}</p>
    {run.error && <p className="message error">{run.error}</p>}
    <RunEvaluation evaluation={run.evaluation} running={run.status === "running"} interrupted={run.status === "interrupted"} />
    <RecoveryPolicy evaluation={run.recovery_evaluation} running={run.status === "running"} interrupted={run.status === "interrupted"} />
    <AssuranceEvaluation security={run.security_evaluation} grounding={run.grounding_evaluation} running={run.status === "running"} interrupted={run.status === "interrupted"} />
    <p>{run.status === "interrupted" ? "Interrupted: final state and fault outcome are unknown. Only last saved state is shown." : "Executed actions and before/after state:"}</p>
    <pre>{JSON.stringify({ steps: run.steps, before: run.initial_state, ...(run.status === "interrupted" ? { last_saved_state: run.final_state } : { after: run.final_state }) }, null, 2)}</pre>
    <details><summary>Recorded model measurements</summary><pre>{JSON.stringify(run.model_telemetry, null, 2)}</pre></details>
  </details>;
}

export function ComparisonReport({ report }: { report: RunComparison }) {
  const a = report.baseline.run, b = report.candidate.run;
  return <article className="comparison-report">
    <div className="comparison-flags">
      <div><strong>Ledger comparison</strong><span>{report.outcomes_comparable ? "Comparable evidence" : "Insufficient or mismatched evidence"}</span></div>
      <div><strong>Recovery comparison</strong><span>{report.recovery_comparable ? "Both faults exercised" : a.scenario === "normal" && b.scenario === "normal" ? "Not applicable to normal runs" : "Insufficient or mismatched evidence"}</span></div>
      <div><strong>Token delta</strong><span>{report.tokens_comparable ? "Complete usage, same model identity" : "Suppressed: see comparison rules"}</span></div>
    </div>
    <p className="comparison-caution">One recorded observation per side. A changed result is evidence to investigate, not a reliability rate.</p>
    <div className="table-scroll" role="region" aria-label="Recorded outcomes" tabIndex={0}>
      <table><caption>Recorded outcomes</caption><thead><tr><th scope="col">Evidence</th><th scope="col">Baseline</th><th scope="col">Candidate</th></tr></thead>
        <tbody>
          <tr><th scope="row">Run</th><td><code>{a.id.slice(0, 8)}</code></td><td><code>{b.id.slice(0, 8)}</code></td></tr>
          <tr><th scope="row">Driver / model</th><td>{a.mode} · {a.model_name ?? "Scripted"}</td><td>{b.mode} · {b.model_name ?? "Scripted"}</td></tr>
          <tr><th scope="row">Scenario</th><td>{readable(a.scenario)}</td><td>{readable(b.scenario)}</td></tr>
          <tr><th scope="row">Execution</th><td>{a.status}</td><td>{b.status}</td></tr>
          <tr><th scope="row">Refund ledger</th><td><Verdict value={a.evaluation?.verdict} /></td><td><Verdict value={b.evaluation?.verdict} /></td></tr>
          <tr><th scope="row">Recovery policy</th><td><Verdict value={a.recovery_evaluation?.verdict} /></td><td><Verdict value={b.recovery_evaluation?.verdict} /></td></tr>
          <tr><th scope="row">Tool-policy audit<small>{report.security_comparable ? "Matching evaluator evidence" : "Unavailable or mismatched grades"}</small></th><td><Verdict value={a.security_evaluation?.verdict} /></td><td><Verdict value={b.security_evaluation?.verdict} /></td></tr>
          <tr><th scope="row">Typed-report grounding<small>{report.grounding_comparable ? "Matching evaluator evidence" : "Unavailable or mismatched grades"}</small></th><td><Verdict value={a.grounding_evaluation?.verdict} /></td><td><Verdict value={b.grounding_evaluation?.verdict} /></td></tr>
          <tr><th scope="row">Fault exercised</th><td>{a.status === "interrupted" ? "Unknown" : a.scenario === "normal" ? "Not selected" : a.fault_injected ? "Yes" : "No"}</td><td>{b.status === "interrupted" ? "Unknown" : b.scenario === "normal" ? "Not selected" : b.fault_injected ? "Yes" : "No"}</td></tr>
          <tr><th scope="row">Usage coverage</th>{[a, b].map(run => <td key={run.id}>{run.model_telemetry
            ? `${run.model_telemetry.reported_usage_requests}/${run.model_telemetry.attempted_requests} requests · ${run.model_telemetry.usage_complete ? "complete" : "partial / unavailable"}`
            : "No model measurements"}</td>)}</tr>
        </tbody>
      </table>
    </div>
    <div className="table-scroll" role="region" aria-label="Observed model measurements" tabIndex={0}>
      <table><caption>Observed model measurements · candidate minus baseline</caption><thead><tr><th scope="col">Measurement</th><th scope="col">Baseline</th><th scope="col">Candidate</th><th scope="col">Delta</th></tr></thead>
        <tbody>{report.measurements.map(metric => <tr key={metric.field}><th scope="row">{fields[metric.field] ?? metric.field}</th>
          <td>{number(metric.baseline)}</td><td>{number(metric.candidate)}</td><td>{metric.delta !== null && metric.delta > 0 ? "+" : ""}{number(metric.delta)}</td></tr>)}</tbody>
      </table>
    </div>
    <p>Request time includes loading, caching, and all attempted requests. Partial token totals are known subtotals. A dash means unavailable, not zero.</p>
    <details><summary>Recorded configuration changes ({report.configuration_changes.length})</summary>
      {report.configuration_changes.length === 0 ? <p>No recorded configuration changes.</p> :
        <div className="table-scroll" role="region" aria-label="Configuration changes" tabIndex={0}><table><thead><tr><th scope="col">Field</th><th scope="col">Baseline</th><th scope="col">Candidate</th></tr></thead>
          <tbody>{report.configuration_changes.map(change => <tr key={change.field}><th scope="row">{change.field}</th><td><code>{String(change.baseline ?? "Not recorded")}</code></td><td><code>{String(change.candidate ?? "Not recorded")}</code></td></tr>)}</tbody>
        </table></div>}
    </details>
    <details><summary>Comparison rules and limitations</summary>
      <ul>{report.checks.map(check => <li key={check.name}><strong>{check.passed ? "Available / matched" : "Unavailable / unmatched"}:</strong> {check.reason}</li>)}</ul>
      {report.notes.map(note => <p key={note}>{note}</p>)}
    </details>
    <div className="comparison-evidence-grid"><Evidence side={report.baseline} label="Baseline" /><Evidence side={report.candidate} label="Candidate" /></div>
  </article>;
}
