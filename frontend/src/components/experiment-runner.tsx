"use client";

import { useId, useState } from "react";
import { apiBaseUrl, type SavedExperiment } from "@/lib/experiments";
import { isAgentRun, phoenixTraceUrl, type AgentRun, type ExecutionMode } from "@/lib/runs";
import { RunEvaluation } from "@/components/run-evaluation";

export function ExperimentRunner({ experiment }: { experiment: SavedExperiment }) {
  const selectId = useId();
  const [mode, setMode] = useState<ExecutionMode>("demo");
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const supported = experiment.agent_version === "refund-v1" &&
    experiment.scenarios.length === 1 &&
    (experiment.scenarios[0] === "normal" || experiment.scenarios[0] === "timeout_after_commit");

  async function loadRuns() {
    const response = await fetch(`${apiBaseUrl}/experiments/${experiment.id}/runs`, {
      cache: "no-store", signal: AbortSignal.timeout(10_000),
    });
    const body: unknown = await response.json();
    if (!response.ok || !Array.isArray(body) || !body.every(isAgentRun)) {
      throw new Error("Could not load saved runs.");
    }
    setRuns(body);
    setLoaded(true);
  }

  async function refresh() {
    setBusy(true);
    setError("");
    setMessage("");
    try { await loadRuns(); }
    catch { setError("Could not load run history. Check the backend and refresh again."); }
    finally { setBusy(false); }
  }

  async function run() {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("Running against a fresh simulated order…");
    try {
      const response = await fetch(`${apiBaseUrl}/experiments/${experiment.id}/runs`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }), signal: AbortSignal.timeout(90_000),
      });
      const body: unknown = await response.json();
      if (!response.ok) {
        const detail = typeof body === "object" && body !== null && "detail" in body &&
          typeof body.detail === "string" ? body.detail : "Could not confirm execution.";
        throw new Error(`${detail} Refresh run history before retrying.`);
      }
      if (!isAgentRun(body)) throw new Error("Unexpected run response. Refresh run history before retrying.");
      setRuns((previous) => [body, ...previous.filter((item) => item.id !== body.id)].slice(0, 10));
      setLoaded(true);
      setMessage(`Execution ${body.status}; task evaluation ${body.evaluation?.verdict.replaceAll("_", " ") ?? "not available"}. Both outcomes have been saved.`);
    } catch (caught) {
      setMessage("");
      setError(caught instanceof Error && !(caught instanceof TypeError) && !(caught instanceof DOMException)
        ? caught.message : "Could not confirm execution. It may still be running. Refresh run history before retrying.");
    } finally { setBusy(false); }
  }

  return (
    <details className="run-panel">
      <summary>Run & inspect saved results</summary>
      <p>Each run starts with a new simulated $49 order. No real payments or orders are accessed.</p>
      <p>Execution supports <code>refund-v1</code> with exactly one scenario: Normal execution or Response lost after refund commits.</p>
      {!supported && <p>Save a matching draft with one supported scenario above. Multiple scenarios and Permission denied cannot execute yet.</p>}
      <label htmlFor={selectId}>Execution driver</label>
      <select id={selectId} value={mode} disabled={busy}
        onChange={(event) => setMode(event.target.value as ExecutionMode)}>
        <option value="demo">Baseline demo — stops on uncertain writes</option>
        <option value="demo_reconcile">Recovery demo — verifies after timeout</option>
        <option value="demo_claim_only">Claim-only demo — intentionally skips tools</option>
        <option value="openai">OpenAI — backend key & model required</option>
      </select>
      {mode === "demo_claim_only" && <p>This scripted negative control claims success without issuing a refund. Its task evaluation should fail. No LLM is used.</p>}
      {mode === "demo_reconcile" && <p>This scripted recovery policy reads the order after an uncertain refund response and avoids refunding again when the read confirms the full amount. No LLM is used.</p>}
      <p>Demo checks the execution path, not model quality. “Completed” means the loop ended normally; it is not a correctness score.</p>
      <button type="button" disabled={busy || !supported} onClick={() => void run()}>
        {busy ? "Working…" : "Run simulated refund"}
      </button>
      <button type="button" disabled={busy} onClick={() => void refresh()}>Refresh run history</button>
      {message && <p role="status">{message}</p>}
      {error && <p role="alert" className="message error">{error}</p>}
      {loaded && runs.length === 0 && <p>No saved runs.</p>}
      <p>Most recent 10 runs. Refresh saved experiments above to update its status.</p>
      {runs.map((saved) => (
        <article className="run-result" key={saved.id}>
          <h3>{saved.mode === "demo" ? "Baseline demo (no LLM)" :
            saved.mode === "demo_reconcile" ? "Recovery demo (no LLM)" :
            saved.mode === "demo_claim_only" ? "Claim-only demo (negative control, no LLM)" : `OpenAI · ${saved.model_name}`}</h3>
          <p><strong>Execution:</strong> {saved.status}</p>
          <p><strong>Scenario:</strong> {saved.scenario === "normal" ? "Normal execution" : "Response lost after refund commits"}</p>
          {saved.scenario === "timeout_after_commit" && <p className="message fault-message">
            <strong>Fault injection:</strong> {saved.status === "running" ? "Awaiting final execution evidence."
              : saved.fault_injected ? "Injected once after the refund changed the sandbox ledger. The driver received an unknown-outcome timeout."
              : "Not triggered. No successful refund operation reached the injection point."}
          </p>}
          <p>{new Date(saved.started_at).toLocaleString()} · <code>{saved.id}</code></p>
          {saved.trace_id ? (
            <p>
              <a href={phoenixTraceUrl(saved.trace_id)} target="_blank" rel="noopener noreferrer">Open trace in Phoenix</a>
              {" · "}<code>{saved.trace_id}</code>
              <br />Export runs in the background. The trace may take a moment to appear; Phoenix must be running.
            </p>
          ) : <p>{saved.status === "running"
            ? "The trace link is saved when execution finishes. Refresh run history to check its outcome."
            : "No trace captured for this run. Enable backend tracing and run again to capture one."}</p>}
          <p><strong>Task:</strong> {saved.task}</p>
          <p><strong>Agent’s claim:</strong> {saved.output ?? "No final answer recorded."}</p>
          {saved.error && <p className="message error">{saved.error}</p>}
          <RunEvaluation evaluation={saved.evaluation} running={saved.status === "running"} />
          <details open>
            <summary>Executed steps ({saved.steps.length})</summary>
            <pre>{JSON.stringify(saved.steps, null, 2)}</pre>
          </details>
          <details open>
            <summary>Actual state before & after</summary>
            <pre>{JSON.stringify({ before: saved.initial_state, after: saved.final_state }, null, 2)}</pre>
          </details>
          {saved.status === "running" && <p>Refresh to check completion. A server interruption can leave a run marked running; crash recovery is not implemented yet.</p>}
        </article>
      ))}
    </details>
  );
}
