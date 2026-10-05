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
- `package.json`: dependencies and commands such as `dev`, `build`, and `lint`.
- `package-lock.json`: resolved dependency versions; `npm ci` installs these versions.
- `tsconfig.json`: TypeScript configuration, including strict checking and the `@/*` import alias for `src/*`.
- `next-env.d.ts`: generated framework type declarations; do not edit manually.
- `next.config.ts`: Next.js framework configuration.
- `eslint.config.mjs`: JavaScript/TypeScript lint rules, including Next.js rules.

`src/` holds application source; `app/` uses Next.js file names to define routes and layouts. React supplies components. Next.js connects those components to routes and renders them. `.tsx` files allow TypeScript and JSX markup together.

## First implementation task

Edit `src/app/page.tsx` yourself. Keep a default-exported React component and have it return:

1. A `<main>` element containing the page content.
2. An `<h1>` reading “Agent Autopsy”.
3. A paragraph describing what the platform tests, in your own words.
4. A list of the three outcomes we will distinguish: the agent's claim, executed tool actions, and actual state changes.

There is no need for state or event handlers in this first task. App Router pages are Server Components by default, which is sufficient for static content. We will introduce a Client Component when we add interactive form state.

Save and observe the page update in the browser. Then run `npm run lint` and `npm run typecheck`. We will review the page before adding a typed reusable component and an experiment form.

## Checks

```bash
npm run lint
npm run typecheck
npm run build
```

## Dependency note

The initial full `npm audit` reports five high-severity entries in the development-only ESLint dependency chain, all stemming from the unpatched `braces` advisory [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm). `npm audit --omit=dev` reports zero vulnerabilities. Keep the matching Next.js lint configuration; the audit's proposed forced downgrade is not an appropriate fix. Recheck when upstream releases a patch.
