# Web front end

React 19 + TypeScript (strict) + Vite, Tailwind (theme from `docs/design/tokens.json`), TanStack Query, React
Router, react-i18next (KM default, EN), typed API clients generated from the services' OpenAPI documents.
Plan: `docs/plans/frontend-plan.md`. Design: `docs/design/`.

Node 20+ (`.nvmrc`: 24). The Makefile picks a Node ≥ 20 from nvm if the default one is older.

| Command | What |
| --- | --- |
| `make web-install` | `npm ci` |
| `make api-types` | `make openapi`, then `src/api/gen/*.ts` (committed, never edited) |
| `make web-dev` | Vite on http://localhost:5173, `/api` proxied to http://localhost (`make up`) |
| `make web-test` | typecheck, ESLint + "no direct fetch" check, Vitest (coverage), build, bundle budget |
| `make web-e2e` | Playwright against `BASE_URL` (default http://localhost) |
| `make web-test-docker` | `make web-test` in a node container |

Docker: the `web` service (nginx, static files, CSP) is routed by Traefik at `PathPrefix(/)` priority 1, so every
`/api` router wins. `make up` serves the app at http://localhost.

## Layout

- `src/api` – `client.ts` (one typed client per service: bearer token from memory, one refresh on 401 through the
  httpOnly cookie, `Idempotency-Key` on the operations listed in `gen/idempotent.ts`, `withKey(key)` to retry the
  same action, `ApiError` from `ErrorOut`), `session.ts`, `types.ts` (schema shortcuts), `gen/` (generated).
- `src/app` – providers, auth (`useAuth`, `useUser().has(...)`), branch switcher state, feature switches, page
  registry (`pages.tsx`: path, sidebar group, gate, lazy screen), router, shell.
- `src/design` – components (Design System frames): Button, Field/Input/Select, SafetyBadge, StatusPill, DataTable,
  Dialog/Drawer/Sheet, ReasonDialog, PinDialog/WitnessDialog, Toasts, states (empty, skeleton after 300 ms, error,
  403/404), Combobox, Scanner, Upload. `/dev/design` shows them all (development builds only).
- `src/features/<module>` – screens. `src/i18n/{km,en}/<ns>.json` – every key in both (a test checks).
  `src/i18n/errors.ts` – KM/EN text for every API error code (designed ones from `error-messages.json`).
- `e2e` – Playwright. `seed.ts` creates (or reuses) a branch and owner / manager / pharmacist / pharmacist2 /
  cashier through the public API and writes `e2e/.auth/seed.json`.

## Rules

- Pages call the API only through `api.<service>.GET/POST/...` (lint fails on `fetch(` or hand-written `/api/`
  URLs). No sample data in screens; a designed field the API does not return is hidden.
- Cost and purchase-price fields are shown only when the API sent them (`hasField`); never computed.
- Every string in KM and EN. Dates DD/MM/YYYY in Asia/Phnom_Penh (`lib/format.ts`). Money from the API.
- Cancel / deactivate ask for a reason where the API takes one. There is no Delete.

## e2e on a stack

On a fresh stack the seed creates the first owner with `docker compose -p $E2E_COMPOSE_PROJECT exec auth ...`
(default project `pharmacy`). On a stack that already has an owner, pass `E2E_OWNER_PHONE`, `E2E_OWNER_PASSWORD`
and `E2E_OWNER_TOTP` (the base32 2FA secret). Logins are rate limited (5/min per phone) and a 2FA code works once
per 30 s, so each role signs in once per run and tests reuse that browser context (`e2e/fixtures.ts`).
