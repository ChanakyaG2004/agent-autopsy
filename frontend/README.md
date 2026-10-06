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
- `.env.example`: optional browser-visible API base URL; copy to `.env.local` to change the default and restart the frontend.
- `package.json`: dependencies and commands such as `dev`, `build`, and `lint`.
- `package-lock.json`: resolved dependency versions; `npm ci` installs these versions.
- `tsconfig.json`: TypeScript configuration, including strict checking and the `@/*` import alias for `src/*`.
- `next-env.d.ts`: generated framework type declarations; do not edit manually.
- `next.config.ts`: Next.js framework configuration.
- `eslint.config.mjs`: JavaScript/TypeScript lint rules, including Next.js rules.

`src/` holds application source; `app/` uses Next.js file names to define routes and layouts. React supplies components. Next.js connects those components to routes and renders them. `.tsx` files allow TypeScript and JSX markup together.

## Current learning checkpoint

The first page is implemented and now uses typed evidence components and an interactive form. Start the backend using its README, then try:

1. Enter an experiment name and agent-version label, select scenarios, and validate.
2. Submit a name made of several spaces to see the backend reject it.
3. Deselect every scenario to see the form's selection check.
4. Stop the backend and submit again to see the network error state.

The page and evidence items are Server Components. Only `ExperimentForm` uses `"use client"`, because it has state and event handlers. Successful validation does not save or run an experiment.

Read [the validation walkthrough](../docs/experiment-validation.md) alongside the component code. The next step adds persistence after reviewing this request flow.

## Checks

```bash
npm run lint
npm run typecheck
npm run build
```

## Dependency note

The initial full `npm audit` reports five high-severity entries in the development-only ESLint dependency chain, all stemming from the unpatched `braces` advisory [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm). `npm audit --omit=dev` reports zero vulnerabilities. Keep the matching Next.js lint configuration; the audit's proposed forced downgrade is not an appropriate fix. Recheck when upstream releases a patch.
