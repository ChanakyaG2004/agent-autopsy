"use client";

import { useEffect, useState } from "react";

import { apiBaseUrl, isSavedExperiment, type SavedExperiment } from "@/lib/experiments";
import { ExperimentRunner } from "@/components/experiment-runner";

type ListState =
  | { status: "loading" }
  | { status: "success"; experiments: SavedExperiment[] }
  | { status: "error"; message: string };

interface ExperimentListProps {
  revision: number;
}

export function ExperimentList({ revision }: ExperimentListProps) {
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 10_000);

    async function loadExperiments() {
      setState({ status: "loading" });
      try {
        const response = await fetch(`${apiBaseUrl}/experiments?limit=20`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Could not load saved experiments.");
        const body: unknown = await response.json();
        if (!Array.isArray(body) || !body.every(isSavedExperiment)) {
          throw new Error("The API returned an unexpected experiment list.");
        }
        if (active && !controller.signal.aborted) {
          setState({ status: "success", experiments: body });
        }
      } catch (error) {
        if (!active) return;
        if (controller.signal.aborted && !timedOut) return;
        setState({
          status: "error",
          message: timedOut
            ? "Loading saved experiments timed out. Try refreshing the list."
            : error instanceof Error && !(error instanceof TypeError)
              ? error.message
              : "Could not reach the API to load saved experiments.",
        });
      } finally {
        clearTimeout(timeout);
      }
    }

    void loadExperiments();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timeout);
    };
  }, [revision, retry]);

  return (
    <section className="experiment-section" aria-labelledby="saved-heading">
      <h2 id="saved-heading">Saved experiments</h2>
      <p>Most recent 20 experiments. Saving a draft does not run an agent.</p>
      <button type="button" onClick={() => setRetry((previous) => previous + 1)}>
        Refresh saved experiments
      </button>
      {state.status === "loading" && <p role="status">Loading saved experiments…</p>}
      {state.status === "error" && <p className="message error" role="alert">{state.message}</p>}
      {state.status === "success" && state.experiments.length === 0 && (
        <p>No saved experiments yet. Create your first draft above.</p>
      )}
      {state.status === "success" && state.experiments.length > 0 && (
        <ul className="saved-experiments">
          {state.experiments.map((experiment) => (
            <li key={experiment.id}>
              <strong>{experiment.name}</strong>
              <p>{experiment.agent_version} · {experiment.scenarios.length} scenario(s) · {experiment.status}</p>
              <p>Created {new Date(experiment.created_at).toLocaleString()}</p>
              <code>{experiment.id}</code>
              <ExperimentRunner experiment={experiment} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
