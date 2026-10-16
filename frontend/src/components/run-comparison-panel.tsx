"use client";

import { useEffect, useState } from "react";
import { apiBaseUrl } from "@/lib/experiments";
import { isRunChoice, isRunComparison, preferredPair, type RunChoice, type RunComparison } from "@/lib/comparisons";
import { ComparisonReport } from "./comparison-report";

type ComparisonState = { status: "loading" } | { status: "error"; message: string } | { status: "success"; report: RunComparison };

function choiceLabel(run: RunChoice): string {
  return `${run.mode} · ${run.scenario} · ${run.status} · ${new Date(run.started_at).toLocaleString()} · ${run.id.slice(0, 8)}`;
}

export function RunComparisonPanel() {
  const [runs, setRuns] = useState<RunChoice[]>([]);
  const [listStatus, setListStatus] = useState<"loading" | "success" | "error">("loading");
  const [revision, setRevision] = useState(0);
  const [baseline, setBaseline] = useState("");
  const [candidate, setCandidate] = useState("");
  const [submitted, setSubmitted] = useState<[string, string] | null>(null);
  const [comparison, setComparison] = useState<ComparisonState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    async function load() {
      setListStatus("loading");
      try {
        const response = await fetch(`${apiBaseUrl}/runs?limit=100`, { cache: "no-store", signal: controller.signal });
        const body: unknown = await response.json();
        if (!response.ok || !Array.isArray(body) || !body.every(isRunChoice)) throw new Error();
        if (!active) return;
        setRuns(body);
        const pair = preferredPair(body);
        setBaseline(pair?.[0] ?? ""); setCandidate(pair?.[1] ?? ""); setSubmitted(pair);
        setListStatus("success");
      } catch { if (active) setListStatus("error"); }
      finally { clearTimeout(timeout); }
    }
    void load();
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [revision]);

  useEffect(() => {
    if (!submitted) return;
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    const [left, right] = submitted;
    async function load() {
      setComparison({ status: "loading" });
      try {
        const query = new URLSearchParams({ baseline_id: left, candidate_id: right });
        const response = await fetch(`${apiBaseUrl}/run-comparisons?${query}`, { cache: "no-store", signal: controller.signal });
        const body: unknown = await response.json();
        if (!response.ok || !isRunComparison(body) || body.baseline.run.id !== left || body.candidate.run.id !== right) throw new Error();
        if (active) setComparison({ status: "success", report: body });
      } catch { if (active) setComparison({ status: "error", message: "Could not load this comparison. Refresh the recorded runs and try again." }); }
      finally { clearTimeout(timeout); }
    }
    void load();
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [submitted]);

  return <section className="comparison-section" aria-labelledby="recorded-comparison-heading">
    <h2 id="recorded-comparison-heading">Recorded runs</h2>
    <p>Choose an earlier observation and a candidate. This reads saved evidence; it never calls a model or changes a result.</p>
    <button className="secondary-button" onClick={() => { setSubmitted(null); setRevision(value => value + 1); }}>Refresh recorded runs</button>
    {listStatus === "loading" && <p role="status">Loading recorded runs…</p>}
    {listStatus === "error" && <p role="alert" className="message error">Could not load recorded runs. Check the API and refresh.</p>}
    {listStatus === "success" && runs.length < 2 && <p>Save at least two executions before comparing. Use the experiments page to run an agent.</p>}
    {listStatus === "success" && runs.length >= 2 && <>
      <form className="comparison-form" onSubmit={event => { event.preventDefault(); if (baseline && candidate && baseline !== candidate) setSubmitted([baseline, candidate]); }}>
        <label>Baseline run<select value={baseline} onChange={event => { setBaseline(event.target.value); setSubmitted(null); }} required>
          <option value="">Choose baseline</option>{runs.map(run => <option value={run.id} key={run.id}>{choiceLabel(run)}</option>)}
        </select></label>
        <label>Candidate run<select value={candidate} onChange={event => { setCandidate(event.target.value); setSubmitted(null); }} required>
          <option value="">Choose candidate</option>{runs.map(run => <option value={run.id} key={run.id}>{choiceLabel(run)}</option>)}
        </select></label>
        <button disabled={!baseline || !candidate || baseline === candidate}>Compare recorded runs</button>
      </form>
      {baseline === candidate && baseline && <p role="status">Choose two different runs.</p>}
      <p className="comparison-fine-print">Latest 100 runs. The initial pair prefers two observations of the same model driver and scenario. Agent labels identify the task contract; recorded prompt and model changes appear below.</p>
      {submitted && comparison.status === "loading" && <p role="status">Loading comparison…</p>}
      {submitted && comparison.status === "error" && <p role="alert" className="message error">{comparison.message}</p>}
      {submitted && comparison.status === "success" && comparison.report.baseline.run.id === submitted[0] && comparison.report.candidate.run.id === submitted[1] && <ComparisonReport report={comparison.report} />}
    </>}
  </section>;
}
