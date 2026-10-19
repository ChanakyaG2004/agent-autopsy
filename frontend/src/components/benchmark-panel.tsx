"use client";

import { useCallback, useEffect, useState } from "react";
import { apiBaseUrl } from "@/lib/experiments";
import { isBenchmarkDetail, isBenchmarkRecord, type BenchmarkDetail, type BenchmarkRecord } from "@/lib/comparisons";
import { phoenixTraceUrl } from "@/lib/runs";
import { BenchmarkQueue } from "./benchmark-queue";
import { Verdict } from "./comparison-report";

type DetailState = { status: "loading" } | { status: "error" } | { status: "success"; report: BenchmarkDetail };
const drivers: Record<string, string> = { demo: "Baseline script", demo_reconcile: "Reconciliation script", demo_claim_only: "Claim-only control" };

export function BenchmarkPanel() {
  const [benchmarks, setBenchmarks] = useState<BenchmarkRecord[]>([]);
  const [listStatus, setListStatus] = useState("loading");
  const [revision, setRevision] = useState(0);
  const refreshCollections = useCallback(() => setRevision(value => value + 1), []);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<DetailState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    async function load() {
      setListStatus("loading");
      try {
        const response = await fetch(`${apiBaseUrl}/benchmarks?limit=20`, { cache: "no-store", signal: controller.signal });
        const body: unknown = await response.json();
        if (!response.ok || !Array.isArray(body) || !body.every(isBenchmarkRecord)) throw new Error();
        if (!active) return;
        setBenchmarks(body); setSelected(body[0]?.id ?? ""); setListStatus("success");
      } catch { if (active) setListStatus("error"); }
      finally { clearTimeout(timeout); }
    }
    void load();
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [revision]);

  useEffect(() => {
    if (!selected) return;
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    async function load() {
      setDetail({ status: "loading" });
      try {
        const response = await fetch(`${apiBaseUrl}/benchmarks/${selected}`, { cache: "no-store", signal: controller.signal });
        const body: unknown = await response.json();
        if (!response.ok || !isBenchmarkDetail(body) || body.id !== selected) throw new Error();
        if (active) setDetail({ status: "success", report: body });
      } catch { if (active) setDetail({ status: "error" }); }
      finally { clearTimeout(timeout); }
    }
    void load();
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [selected, revision]);

  const report = detail.status === "success" && detail.report.id === selected ? detail.report : null;
  const counts = report?.summary.overall;
  return <section className="comparison-section" aria-labelledby="benchmark-comparison-heading">
    <h2 id="benchmark-comparison-heading">Scripted policy benchmark</h2>
    <p>One distinct refund task across three scenarios and three scripted policies. These controls exercise the harness; they do not measure a live model’s reliability. Repetitions repeat the same cases.</p>
    <BenchmarkQueue onFinished={refreshCollections} />
    <button className="secondary-button" onClick={() => { setSelected(""); setRevision(value => value + 1); }}>Refresh saved benchmarks</button>
    {listStatus === "loading" && <p role="status">Loading saved benchmarks…</p>}
    {listStatus === "error" && <p role="alert" className="message error">Could not load benchmarks. Check the API and refresh.</p>}
    {listStatus === "success" && benchmarks.length === 0 && <p>No benchmark has been collected. Queue a scripted benchmark above to create the first collection.</p>}
    {listStatus === "success" && benchmarks.length > 0 && <>
      <label className="benchmark-select">Saved benchmark (latest 20)<select value={selected} onChange={event => setSelected(event.target.value)}>
        {benchmarks.map(row => <option key={row.id} value={row.id}>{row.suite_version} · {row.status} · {new Date(row.started_at).toLocaleString()} · {row.id.slice(0, 8)}</option>)}
      </select></label>
      {detail.status === "loading" && <p role="status">Loading benchmark evidence…</p>}
      {detail.status === "error" && <p role="alert" className="message error">Could not load this benchmark. Refresh to try again.</p>}
      {report && counts && <>
        <p><strong>Collection: {report.status}.</strong> {counts.recorded}/{counts.planned} terminal runs recorded · {counts.infrastructure_failed} infrastructure failures · {counts.pending} pending.</p>
        <p>Execution completion, ledger correctness, and recovery policy are independent. A safe refusal can pass policy while failing the refund goal.</p>
        <div className="table-scroll" role="region" aria-label="Scripted policy counts" tabIndex={0}>
          <table><caption>Counts by policy · every denominator stays visible</caption><thead><tr>
            <th scope="col">Policy</th><th scope="col">Recorded / planned</th><th scope="col">Execution completed / planned</th>
            <th scope="col">Ledger passed / planned</th><th scope="col">Recovery pass / fail / unavailable / N/A</th><th scope="col">Fault exercised / selected</th><th scope="col">Infrastructure failures / pending</th>
          </tr></thead><tbody>{report.summary.drivers.map(({ mode, counts: c }) => <tr key={mode}>
            <th scope="row">{drivers[mode]}</th><td>{c.recorded} / {c.planned}</td><td>{c.execution_completed} / {c.planned}</td>
            <td>{c.ledger_passed} / {c.planned}<small>{c.ledger_failed} failed · {c.ledger_not_evaluable} unavailable</small></td>
            <td>{c.recovery_passed} / {c.recovery_failed} / {c.recovery_not_evaluable} / {c.recovery_not_applicable}<small>Of {c.recorded} recorded runs</small></td>
            <td>{c.fault_injected} / {c.fault_selected}</td><td>{c.infrastructure_failed} / {c.pending}</td>
          </tr>)}</tbody></table>
        </div>
        <details className="benchmark-items"><summary>Inspect {report.items.length} saved cell records</summary>
          <div className="table-scroll" role="region" aria-label="Benchmark cells" tabIndex={0}><table><thead><tr>
            <th scope="col">Policy / case</th><th scope="col">Collection / execution</th><th scope="col">Ledger</th><th scope="col">Recovery</th><th scope="col">Tool policy / typed report</th><th scope="col">Fault exercised</th><th scope="col">Evidence</th>
          </tr></thead><tbody>{report.items.map(item => <tr key={item.id}>
            <th scope="row">{drivers[item.mode]}<small>{item.case_key.replaceAll("_", " ")} · repetition {item.repetition}</small></th>
            <td>{item.status} / {item.run?.status ?? "No run"}{item.error && <small>{item.error}</small>}</td>
            <td><Verdict value={item.run?.evaluation?.verdict} /></td><td><Verdict value={item.run?.recovery_evaluation?.verdict} /></td>
            <td><Verdict value={item.run?.security_evaluation?.verdict} /> / <Verdict value={item.run?.grounding_evaluation?.verdict} /></td>
            <td>{!item.run ? "Unavailable" : item.run.status === "interrupted" ? "Unknown" : item.run.scenario === "normal" ? "Not selected" : item.run.fault_injected ? "Yes" : "No"}</td>
            <td>{item.run?.trace_id && <a href={phoenixTraceUrl(item.run.trace_id)} target="_blank" rel="noopener noreferrer">Phoenix trace</a>}
              <details><summary>Saved evidence</summary><pre>{JSON.stringify({ run_id: item.run_id, run: item.run }, null, 2)}</pre></details></td>
          </tr>)}</tbody></table></div>
        </details>
        <details><summary>Reproducibility manifest</summary><p>The saved suite, schedule, evaluator versions, source hashes, and environment describe this collection.</p><pre>{JSON.stringify(report.manifest, null, 2)}</pre></details>
      </>}
    </>}
  </section>;
}
