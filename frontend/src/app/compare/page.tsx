import Link from "next/link";
import { RunComparisonPanel } from "@/components/run-comparison-panel";
import { BenchmarkPanel } from "@/components/benchmark-panel";

export default function ComparePage() {
  return <main className="comparison-page">
    <nav aria-label="Main"><Link href="/">← Experiments</Link></nav>
    <h1>Compare execution evidence</h1>
    <p>Inspect what changed between saved observations, then check each result against the underlying actions, state, and Phoenix trace.</p>
    <RunComparisonPanel />
    <BenchmarkPanel />
  </main>;
}
