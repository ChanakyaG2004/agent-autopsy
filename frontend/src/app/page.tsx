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
        <li>
          <strong>Agent&apos;s claim:</strong> What the agent tells the user it
          accomplished.
        </li>
        <li>
          <strong>Executed tool actions:</strong> Which tool operations actually
          ran, including retries and errors.
        </li>
        <li>
          <strong>Actual state changes:</strong> What changed in the system, such
          as the number and amounts of recorded refunds.
        </li>
      </ul>
    </main>
  );
}
