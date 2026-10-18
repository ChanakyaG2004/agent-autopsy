"use client";

import { useCallback, useId, useState } from "react";
import { apiBaseUrl, type SavedExperiment } from "@/lib/experiments";
import { isAgentRun, phoenixTraceUrl, type AgentRun, type ExecutionMode } from "@/lib/runs";
import { RunEvaluation } from "@/components/run-evaluation";
import { AssuranceEvaluation } from "./assurance-evaluation";
import { JobMonitor } from "./job-monitor";
import { isJob, jobActive, submitJob, type Job } from "@/lib/jobs";
import { RecoveryPolicy } from "@/components/recovery-evaluation";

export function ExperimentRunner({ experiment }: { experiment: SavedExperiment }) {
  const selectId = useId();
  const [mode, setMode] = useState<ExecutionMode>("ollama");
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const supported = experiment.agent_version === "refund-v1" &&
    experiment.scenarios.length === 1 &&
    (experiment.scenarios[0] === "normal" || experiment.scenarios[0] === "timeout_after_commit" || experiment.scenarios[0] === "permission_denied");

  const loadRuns = useCallback(async () => {
    const response = await fetch(`${apiBaseUrl}/experiments/${experiment.id}/runs`, {
      cache: "no-store", signal: AbortSignal.timeout(10_000),
    });
    const body: unknown = await response.json();
    if (!response.ok || !Array.isArray(body) || !body.every(isAgentRun)) {
      throw new Error("Could not load saved runs.");
    }
    setRuns(body);
    setLoaded(true);
  }, [experiment.id]);

  const finished = useCallback(() => {
    setMessage("Background processing finished. Loading saved evidence…");
    void loadRuns().then(() => setMessage("Saved results refreshed.")).catch(() => setError("Refresh run history to load saved evidence."));
  }, [loadRuns]);

  async function refresh() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await loadRuns();
      const response = await fetch(`${apiBaseUrl}/jobs?experiment_id=${experiment.id}&limit=10`, { cache: "no-store", signal: AbortSignal.timeout(10_000) });
      const body: unknown = await response.json();
      if (!response.ok || !Array.isArray(body) || !body.every(isJob)) throw new Error();
      setJob(body.find(jobActive) ?? body[0] ?? null);
    }
    catch { setError("Could not load run history. Check the backend and refresh again."); }
    finally { setBusy(false); }
  }

  async function run() {
    if (busy || jobActive(job)) return;
    setBusy(true);
    setError("");
    setMessage("Saving background job…");
    try {
      const body = await submitJob(`/experiments/${experiment.id}/jobs`, { mode }, `agent-autopsy:run-submission:${experiment.id}`);
      if (body.kind !== "run" || body.experiment_id !== experiment.id) throw new Error("Unexpected job response. Refresh jobs before retrying.");
      setJob(body);
      if (jobActive(body)) setMessage("Job accepted. A separate worker will execute it; leaving this page does not cancel it.");
      else { await loadRuns(); setMessage("This request was already processed. Saved results refreshed."); }
    } catch (caught) {
      setMessage("");
      setError(caught instanceof Error && !(caught instanceof TypeError) && !(caught instanceof DOMException)
        ? caught.message : "Could not confirm job acceptance. Refresh jobs; retrying the same settings will reuse the saved request ID.");
    } finally { setBusy(false); }
  }

  return (
    <details className="run-panel" onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open && !loaded && !busy) void refresh(); }}>
      <summary>Run & inspect saved results</summary>
      <p>Each run starts with a new simulated $49 order. No real payments or orders are accessed.</p>
      <p>Execution supports <code>refund-v1</code> with exactly one scenario: Normal execution, Response lost after refund commits, or Permission denied.</p>
      {!supported && <p>Save a matching draft with exactly one supported scenario above. Multiple scenarios cannot execute yet.</p>}
      <label htmlFor={selectId}>Execution driver</label>
      <select id={selectId} value={mode} disabled={busy || jobActive(job)}
        onChange={(event) => setMode(event.target.value as ExecutionMode)}>
        <option value="ollama">Ollama — local model, no API key</option>
        <option value="demo">Baseline demo — stops on tool errors</option>
        <option value="demo_reconcile">Recovery demo — verifies timeouts, respects denials</option>
        <option value="demo_claim_only">Claim-only demo — intentionally skips tools</option>
        <option value="openai">OpenAI — backend key & model required</option>
      </select>
      {mode === "ollama" && <p>Runs a real model through your local Ollama service. No hosted inference fee or API key. The backend selects the installed model; cold starts can take longer.</p>}
      {mode === "demo_claim_only" && <p>This scripted negative control claims success without issuing a refund. Its task evaluation should fail. No LLM is used.</p>}
      {mode === "demo_reconcile" && <p>This scripted recovery policy verifies uncertain writes and stops with a final refusal after permission denial. No LLM is used.</p>}
      <p>Demo checks the execution path, not model quality. “Completed” means the loop ended normally; it is not a correctness score.</p>
      <button type="button" disabled={busy || !supported || jobActive(job)} onClick={() => void run()}>
        {busy ? "Working…" : "Queue simulated refund"}
      </button>
      <button type="button" disabled={busy} onClick={() => void refresh()}>Refresh runs and jobs</button>
      {message && <p role="status">{message}</p>}
      {error && <p role="alert" className="message error">{error}</p>}
      {job && <JobMonitor job={job} onChange={setJob} onFinished={finished} />}
      {loaded && runs.length === 0 && <p>No saved runs.</p>}
      <p>Most recent 10 runs. Refresh saved experiments above to update its status.</p>
      {runs.map((saved) => (
        <article className="run-result" key={saved.id}>
          <h3>{saved.mode === "demo" ? "Baseline demo (no LLM)" :
            saved.mode === "demo_reconcile" ? "Recovery demo (no LLM)" :
            saved.mode === "demo_claim_only" ? "Claim-only demo (negative control, no LLM)" :
            saved.mode === "ollama" ? `Ollama · ${saved.model_name}` : `OpenAI · ${saved.model_name}`}</h3>
          <p><strong>Execution:</strong> {saved.status}</p>
          <p><strong>Scenario:</strong> {saved.scenario === "normal" ? "Normal execution" : saved.scenario === "permission_denied" ? "Permission denied" : "Response lost after refund commits"}</p>
          {saved.scenario === "permission_denied" && <p className="message fault-message">
            <strong>Permission boundary:</strong> {saved.status === "running" ? "Awaiting final execution evidence."
              : saved.status === "interrupted" ? "Fault outcome is unknown after interruption."
              : saved.fault_injected ? "Refund rejected before mutation. All refund retries remain denied."
              : "Not exercised. No valid refund attempt reached the permission boundary."}
            {" "}A safe refusal can pass the recovery policy while the refund goal remains unmet.
          </p>}
          {saved.scenario === "timeout_after_commit" && <p className="message fault-message">
            <strong>Fault injection:</strong> {saved.status === "running" ? "Awaiting final execution evidence."
              : saved.status === "interrupted" ? "Fault outcome is unknown after interruption."
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
          <RunEvaluation evaluation={saved.evaluation} running={saved.status === "running"} interrupted={saved.status === "interrupted"} />
          <RecoveryPolicy evaluation={saved.recovery_evaluation} running={saved.status === "running"} interrupted={saved.status === "interrupted"} />
          <AssuranceEvaluation security={saved.security_evaluation} grounding={saved.grounding_evaluation} running={saved.status === "running"} interrupted={saved.status === "interrupted"} />
          <details open>
            <summary>Executed steps ({saved.steps.length})</summary>
            <pre>{JSON.stringify(saved.steps, null, 2)}</pre>
          </details>
          <details open>
            <summary>{saved.status === "interrupted" ? "Last saved state — final state unknown" : "Actual state before & after"}</summary>
            <pre>{JSON.stringify(saved.status === "interrupted" ? { before: saved.initial_state, last_saved_state: saved.final_state } : { before: saved.initial_state, after: saved.final_state }, null, 2)}</pre>
          </details>
          {saved.status === "running" && <p>Refresh to check completion. Durable jobs recover expired worker ownership. An interrupted execution is marked explicitly instead of replayed; inline CLI executions have no worker lease.</p>}
        </article>
      ))}
    </details>
  );
}
