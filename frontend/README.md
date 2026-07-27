# Frontend

The dashboard and admin UI: a Vite + React 19 + TypeScript SPA, styled with Tailwind v4 and
shadcn/ui components built on Radix primitives.

It builds into `../static/app/`, which Flask serves through the two-line Jinja shells in
`../templates/`. Those templates only set a `<title>` and mount `#root` — all data fetching,
filtering and error handling happens client-side against the JSON API.

## Commands

```bash
pnpm install

pnpm dev      # hot reload against a Flask backend running on :5000
pnpm build    # tsc -b && vite build -> ../static/app/
pnpm lint     # oxlint
```

`../static/app/` is gitignored — the multi-stage `Dockerfile` builds it during the image build. For
local development against a Flask server you need to run `pnpm build` yourself after editing
anything here (or use `pnpm dev`), otherwise Flask serves a stale bundle, or none at all on a fresh
checkout.

## Layout

```
src/
├── pages/        one file per route (see App.tsx)
├── components/   app-specific components, plus ui/ for shadcn primitives
├── lib/          API clients, shared hooks, formatting helpers
└── hooks/
```

Two API clients, split by audience: `lib/api.ts` for the public `/health` and `/keys` endpoints, and
`lib/admin-api.ts` for everything under `/admin/api/`. Shared health state comes from `useHealth()`,
lifted into a context by `lib/health-context.tsx`, which self-refreshes on the backend's own
`poll_interval_seconds`.

## Conventions

- Format timestamps with `formatDateTime()`/`formatTime()` from `lib/format.ts`, passing the
  tailnet's configured timezone from `useTimezone()` — not bare `toLocaleString()`, which renders in
  the viewer's browser timezone rather than the one the app is configured for.
- Surface load failures with `<Alert>` (`components/ui/alert.tsx`) and transient action results with
  `useToast()`. Every `fetch` needs a `.catch` that sets an error state — a bare `.then()` leaves the
  page on its loading skeleton forever.
- Derive error text with `errorMessage(err, fallback)` from `lib/admin-api.ts`.
- Confirm destructive actions with `<ConfirmDialog>`, not `window.confirm`.

Note the `<main>` overflow constraint documented in the repository root `CLAUDE.md` before touching
`components/layout.tsx`.

## Linting

`pnpm lint` runs oxlint with the rules in `.oxlintrc.json`. Type-aware rules are not enabled; `tsc -b`
(run by `pnpm build`, and as its own CI step) is what catches type errors.
