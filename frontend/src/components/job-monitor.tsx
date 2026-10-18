"use client";

import { useEffect, useState } from "react";
import { apiBaseUrl } from "@/lib/experiments";
import { isJob, jobActive, type Job } from "@/lib/jobs";

export function JobMonitor({ job, onChange, onFinished }: {
  job: Job; onChange: (job: Job) => void; onFinished: () => void;
}) {
  const [error, setError] = useState("");
  const id = job.id, status = job.status;
  useEffect(() => {
    if (status !== "queued" && status !== "running") return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController;
    async function poll() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10_000);
      try {
        const response = await fetch(`${apiBaseUrl}/jobs/${id}`, { cache: "no-store", signal: controller.signal });
        const body: unknown = await response.json();
        if (!response.ok || !isJob(body) || body.id !== id) throw new Error();
        if (!active) return;
        setError(""); onChange(body);
        if (!jobActive(body)) { onFinished(); return; }
      } catch { if (active) setError("Job status is temporarily unavailable. Monitoring will retry; this does not resubmit work."); }
      finally { clearTimeout(timeout); }
      if (active) timer = setTimeout(poll, 2000);
    }
    timer = setTimeout(poll, 1000);
    return () => { active = false; clearTimeout(timer); controller?.abort(); };
  }, [id, status, onChange, onFinished]);

  return <section className="job-status" aria-label="Background job">
    <p role="status"><strong>Job: {job.status}.</strong> {job.status === "queued" ? "Saved and waiting for a worker. You can leave this page."
      : job.status === "running" ? "A worker owns this execution. You can leave and refresh later."
      : job.status === "succeeded" ? "Processing finished. Inspect the saved execution and evaluation results below."
      : job.status === "interrupted" ? "The worker was interrupted. Unknown executions were not replayed automatically."
      : "Processing could not finish. Review the error and saved evidence before starting new work."}</p>
    {job.error && <p className="message error">{job.error}</p>}
    {error && jobActive(job) && <p role="alert">{error}</p>}
    <details><summary>Job receipt</summary><p><code>{job.id}</code> · accepted {new Date(job.created_at).toLocaleString()}</p>
      <p>Worker claims: {job.attempts}. Execution status and evaluation grades are separate from processing status.</p>
    </details>
  </section>;
}
