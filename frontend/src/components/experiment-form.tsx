"use client";

import { useState, type FormEvent } from "react";

import { ExperimentList } from "@/components/experiment-list";
import { apiBaseUrl, isSavedExperiment, type ExperimentDraft, type Scenario } from "@/lib/experiments";

type SubmissionState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success"; message: string }
  | { status: "error"; message: string };

const scenarioOptions: { value: Scenario; label: string }[] = [
  { value: "normal", label: "Normal execution" },
  { value: "timeout_after_commit", label: "Response lost after refund commits" },
  { value: "permission_denied", label: "Permission denied" },
];

export function ExperimentForm() {
  const [name, setName] = useState("");
  const [agentVersion, setAgentVersion] = useState("");
  const [scenarios, setScenarios] = useState<Scenario[]>(["normal"]);
  const [submission, setSubmission] = useState<SubmissionState>({ status: "idle" });
  const [listRevision, setListRevision] = useState(0);
  const isSubmitting = submission.status === "submitting";

  function toggleScenario(scenario: Scenario) {
    setScenarios((previous) =>
      previous.includes(scenario)
        ? previous.filter((value) => value !== scenario)
        : [...previous, scenario],
    );
    setSubmission({ status: "idle" });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) return;
    if (scenarios.length === 0) {
      setSubmission({ status: "error", message: "Select at least one scenario." });
      return;
    }

    setSubmission({ status: "submitting" });
    const draft: ExperimentDraft = { name, agent_version: agentVersion, scenarios };

    try {
      const response = await fetch(`${apiBaseUrl}/experiments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
        signal: AbortSignal.timeout(10_000),
      });

      if (!response.ok) {
        setSubmission({
          status: "error",
          message:
            response.status === 422
              ? "Check your entries: the name needs 3–80 characters, the agent version needs 1–80, and at least one scenario must be selected. Spaces alone do not count."
              : "Could not confirm that the experiment was saved. Refresh saved experiments before retrying.",
        });
        return;
      }

      const body: unknown = await response.json();
      if (!isSavedExperiment(body)) {
        setSubmission({ status: "error", message: "The API returned an unexpected response. Refresh saved experiments to check whether the draft was saved." });
        return;
      }

      setSubmission({ status: "success", message: `Saved “${body.name}” as draft ${body.id}. No agent has been run.` });
      setListRevision((previous) => previous + 1);
    } catch (error) {
      setSubmission({
        status: "error",
        message:
          error instanceof SyntaxError
            ? "The API returned an unexpected response. Refresh saved experiments before retrying."
            : error instanceof DOMException && error.name === "TimeoutError"
            ? "The save request timed out. It may have succeeded. Refresh saved experiments before retrying."
            : "Could not confirm the save. Check the backend, then refresh saved experiments before retrying.",
      });
    }
  }

  return (
    <section className="experiment-section" aria-labelledby="experiment-heading">
      <h2 id="experiment-heading">Create an experiment draft</h2>
      <p id="experiment-help">
        Save a configuration, then run it from the saved list. Execution currently
        supports refund-v1 with Normal execution only; the fault choices are planned.
        Saving does not execute tools.
      </p>

      <form onSubmit={handleSubmit} aria-busy={isSubmitting} aria-describedby="experiment-help">
        <fieldset disabled={isSubmitting} className="form-fields">
          <legend>Experiment configuration</legend>
          <label htmlFor="experiment-name">Experiment name</label>
          <input
            id="experiment-name"
            name="name"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setSubmission({ status: "idle" });
            }}
            minLength={3}
            maxLength={80}
            required
            placeholder="Refund recovery baseline"
          />

          <label htmlFor="agent-version">Agent version label</label>
          <input
            id="agent-version"
            name="agent_version"
            value={agentVersion}
            onChange={(event) => {
              setAgentVersion(event.target.value);
              setSubmission({ status: "idle" });
            }}
            maxLength={80}
            required
            placeholder="refund-v1"
          />

          <fieldset className="scenario-fields">
            <legend>Scenarios</legend>
            {scenarioOptions.map((scenario) => (
              <label key={scenario.value} className="checkbox-label">
                <input
                  type="checkbox"
                  name="scenarios"
                  value={scenario.value}
                  checked={scenarios.includes(scenario.value)}
                  onChange={() => toggleScenario(scenario.value)}
                />
                {scenario.label}
              </label>
            ))}
          </fieldset>

          <button type="submit">{isSubmitting ? "Saving…" : "Save experiment draft"}</button>
        </fieldset>

        {submission.status === "submitting" && <p role="status">Saving experiment draft…</p>}
        {submission.status === "error" && <p className="message error" role="alert">{submission.message}</p>}
        {submission.status === "success" && <p className="message success" role="status">{submission.message}</p>}
      </form>
      <ExperimentList revision={listRevision} />
    </section>
  );
}
