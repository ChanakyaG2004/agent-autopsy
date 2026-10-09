# Frontend

The Next.js App Router application uses React and TypeScript, with plain CSS and ESLint.

This application will own pages, forms, navigation, and presentation of experiment results, including loading and error states. It will request application data through the FastAPI API.

Experiment execution, tool authorization, database access, and model-provider credentials belong in the backend.

## Run locally

From the repository root:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. Stop the server with Ctrl+C.

The root `.nvmrc` records the Node.js version used for setup. If you use nvm, run `nvm install` and `nvm use` from the repository root before installing frontend dependencies.

## Files

- `src/app/page.tsx`: the React component displayed at `/`; this is the first file you will edit.
- `src/app/layout.tsx`: the shared document layout, wrapping pages in `<html>` and `<body>`.
- `src/app/globals.css`: global styles imported by the root layout.
- `src/components/evidence-item.tsx`: reusable evidence list item with typed title and description props.
- `src/components/experiment-form.tsx`: interactive configuration form, submission state, and a direct API request.
- `src/components/experiment-list.tsx`: fetches and displays recent saved experiments with loading, empty, and error states.
- `src/components/experiment-runner.tsx`: execution driver selection, explicit run action, saved run history and evidence inspection.
- `src/lib/runs.ts`: run response contract and runtime response validation.
- `src/lib/experiments.ts`: shared frontend contracts, API URL, and response type guard.
- `.env.example`: optional browser-visible API base URL; copy to `.env.local` to change the default and restart the frontend.
- `package.json`: dependencies and commands such as `dev`, `build`, and `lint`.
- `package-lock.json`: resolved dependency versions; `npm ci` installs these versions.
- `tsconfig.json`: TypeScript configuration, including strict checking and the `@/*` import alias for `src/*`.
- `next-env.d.ts`: generated framework type declarations; do not edit manually.
- `next.config.ts`: Next.js framework configuration.
- `eslint.config.mjs`: JavaScript/TypeScript lint rules, including Next.js rules.

`src/` holds application source; `app/` uses Next.js file names to define routes and layouts. React supplies components. Next.js connects those components to routes and renders them. `.tsx` files allow TypeScript and JSX markup together.

## Current learning checkpoint

The page saves drafts and executes the supported normal refund scenario. Start PostgreSQL and the backend using the backend README, then try:

1. Enter an experiment name and agent-version label, select scenarios, and save a draft.
2. Submit a name made of several spaces to see the backend reject it.
3. Deselect every scenario to see the form's selection check.
4. Stop the backend and submit again to see the network error state.
5. Restart the backend, refresh the page, and verify the saved draft remains in the list.
6. Save a draft with `refund-v1` and only Normal execution selected. Open its run panel and use the deterministic demo.
7. Inspect the tool steps and state snapshots. Reload, reopen the panel, and click Refresh run history to retrieve the saved result.

The page and evidence items are Server Components. `ExperimentForm`, `ExperimentList`, and `ExperimentRunner` use `"use client"` for state, events, and browser fetching. Saving a draft does not run an agent. Failed save or execution responses can be ambiguous; refresh the relevant history before retrying rather than assuming nothing was stored. The run request waits up to 90 seconds in the browser; aborting that wait does not cancel backend execution.

Read [the persistence walkthrough](../docs/experiment-persistence.md) and [execution walkthrough](../docs/agent-execution.md) alongside the component code. The list displays up to 20 experiments and refreshes after a save. Run panels retrieve the latest 10 runs on demand. Refresh saved experiments to update the experiment status after running.

## Checks

```bash
npm run lint
npm run typecheck
npm run build
```

## Dependency note

The initial full `npm audit` reports five high-severity entries in the development-only ESLint dependency chain, all stemming from the unpatched `braces` advisory [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm). `npm audit --omit=dev` reports zero vulnerabilities. Keep the matching Next.js lint configuration; the audit's proposed forced downgrade is not an appropriate fix. Recheck when upstream releases a patch.
