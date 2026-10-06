import { EvidenceItem } from "@/components/evidence-item";
import { ExperimentForm } from "@/components/experiment-form";

export default function Home() {
  return (
    <main>
      <h1>Agent Autopsy</h1>
      <p>
        Test AI agents under controlled API failures, inspect their execution
        traces, and compare what they report with what actually changed. Our
        first test subject is an agent that cancels orders and issues refunds.
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
