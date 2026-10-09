"use client";

import { useId, useState } from "react";
import { apiBaseUrl, type SavedExperiment } from "@/lib/experiments";
import { isAgentRun, type AgentRun } from "@/lib/runs";

export function ExperimentRunner({ experiment }: { experiment: SavedExperiment }) {
  const selectId = useId();
  const [mode, setMode] = useState<"demo" | "openai">("demo");
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const supported = experiment.agent_version === "refund-v1" &&
    experiment.scenarios.length === 1 && experiment.scenarios[0] === "normal";

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
      setMessage(`Execution ${body.status}. Its result has been saved.`);
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
      <p>Execution supports <code>refund-v1</code> with only <code>normal</code> selected.</p>
      {!supported && <p>Save a matching draft above to run this milestone. Fault scenarios are not implemented yet.</p>}
      <label htmlFor={selectId}>Execution driver</label>
      <select id={selectId} value={mode} disabled={busy}
        onChange={(event) => setMode(event.target.value as "demo" | "openai")}>
        <option value="demo">Deterministic demo — no LLM</option>
        <option value="openai">OpenAI — backend key & model required</option>
      </select>
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
          <h3>{saved.mode === "demo" ? "Deterministic demo (no LLM)" : `OpenAI · ${saved.model_name}`} · {saved.status}</h3>
          <p>{new Date(saved.started_at).toLocaleString()} · <code>{saved.id}</code></p>
          <p><strong>Task:</strong> {saved.task}</p>
          <p><strong>Agent’s claim:</strong> {saved.output ?? "No final answer recorded."}</p>
          {saved.error && <p className="message error">{saved.error}</p>}
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
