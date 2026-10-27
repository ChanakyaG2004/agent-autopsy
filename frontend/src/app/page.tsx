import { EvidenceItem } from "@/components/evidence-item";
import { ExperimentForm } from "@/components/experiment-form";
import Link from "next/link";
import { RecordedDemo } from "@/components/recorded-demo";

export default function Home() {
  if (process.env.AGENT_AUTOPSY_PUBLIC_DEMO === "true") return <RecordedDemo />;
  return (
    <main>
      <nav aria-label="Main"><Link href="/compare">Compare saved runs and policies →</Link></nav>
      <h1>Agent Autopsy</h1>
      <p>
        Test AI agents under controlled API failures, inspect their execution
        traces, and compare what they report with what actually changed. Our
        first test subject is an agent that issues refunds on simulated orders.
      </p>

      <h2>Three kinds of execution evidence</h2>
      <ul>
        <EvidenceItem
          title="Agent’s claim"
          description="What the agent tells the user it accomplished."
        />
        <EvidenceItem
          title="Executed tool actions"
          description="Which tool operations actually ran, including retries and errors."
        />
        <EvidenceItem
          title="Actual state changes"
          description="What changed in the system, such as the number and amounts of recorded refunds."
        />
      </ul>

      <ExperimentForm />
    </main>
  );
}
