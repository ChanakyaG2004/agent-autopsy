"use client";

import { useEffect, useState } from "react";
import { apiBaseUrl } from "@/lib/experiments";
import { isJob, jobActive, submitJob, type Job } from "@/lib/jobs";
import { JobMonitor } from "./job-monitor";

export function BenchmarkQueue({ onFinished }: { onFinished: () => void }) {
  const [job, setJob] = useState<Job | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    async function load() {
      try {
        const response = await fetch(`${apiBaseUrl}/jobs?kind=benchmark&limit=20`, { cache: "no-store", signal: controller.signal });
        const body: unknown = await response.json();
        if (!response.ok || !Array.isArray(body) || !body.every(isJob)) throw new Error();
        if (active) { setJob(body.find(jobActive) ?? body[0] ?? null); setLoaded(true); setError(""); }
      } catch { if (active) setError("Could not load benchmark jobs. Refresh before queueing work."); }
      finally { clearTimeout(timeout); }
    }
    void load();
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [revision]);
  async function queue() {
    if (!loaded || busy || jobActive(job)) return;
    setBusy(true); setError("");
    try {
      setJob(await submitJob("/benchmark-jobs", { repetitions: 1 }, "agent-autopsy:benchmark-submission"));
      onFinished(); // Refresh the newly committed schedule, not just finished results.
    } catch (error) { setError(error instanceof Error ? error.message : "Could not confirm acceptance. Refresh jobs before retrying."); }
    finally { setBusy(false); }
  }
  return <div className="benchmark-queue">
    <button disabled={!loaded || busy || jobActive(job)} onClick={() => void queue()}>{busy ? "Saving job…" : "Queue scripted benchmark (9 cells)"}</button>
    <button className="secondary-button" disabled={busy} onClick={() => { setLoaded(false); setRevision(value => value + 1); }}>Refresh benchmark jobs</button>
    <p>This queues one repetition using scripted policies. It makes no LLM requests.</p>
    {error && <p role="alert" className="message error">{error}</p>}
    {job && <JobMonitor job={job} onChange={setJob} onFinished={onFinished} />}
  </div>;
}
