# Pharmacy System Management

Multi-branch pharmacy system: POS with FEFO batches, prescriptions,
controlled-drug register, purchasing, transfers, reports, Telegram and AI help.
Built as 14 FastAPI microservices behind Traefik. Spec: [docs/spec.md](docs/spec.md).

## Quick start

```bash
make env      # creates .env from .env.example – change the passwords
make up       # builds and starts everything
```

Check a service: http://localhost/api/sales/v1/health
API docs per service: http://localhost/api/<prefix>/v1/docs (use "Authorize" with an access token)

```bash
make owner    # create the first owner account
make smoke    # login, protected routes, logout – through Traefik
make test     # starts test Postgres + Redis, then lint + all tests
make test-docker  # the same inside a python:3.12 container (no local Python needed)
```

Log in: `POST /api/auth/v1/login` with `{"phone": "...", "password": "..."}`, then send
`Authorization: Bearer <access_token>` on every other call.

The owner and branch managers must use two-factor login (Google Authenticator,
Microsoft Authenticator, 2FAS…). The first login returns `mfa_setup_required: true`:
call `POST /api/auth/v1/2fa/setup`, scan the QR code (`qr_svg`) or type the `secret`,
then `POST /api/auth/v1/2fa/enable` with the 6-digit code. Later logins return
`mfa_required: true` and an `mfa_token`; send it with the code to `POST /api/auth/v1/login/2fa`.
`make smoke` walks you through this.

## Services

| Service | Prefix | Owns |
| --- | --- | --- |
| auth | `/api/auth/v1` | Users, roles, permissions, sessions, PIN, audit log |
| branch | `/api/branch/v1` | Branches, branch settings, feature switches |
| catalog | `/api/catalog/v1` | Medicines, pack units, categories, brands, promotions, hampers, imports |
| inventory | `/api/inventory/v1` | Batches, stock per branch, movements, transfers, shrinkage, opening stock, recalls |
| stockcount | `/api/stockcount/v1` | Stock takes, count lines, double count, approval |
| prescription | `/api/prescription/v1` | Patients, doctors, prescriptions, Rx items, dispensing balance |
| controlled | `/api/controlled/v1` | Controlled-drug register (append-only, hash-chained), witness, discrepancies |
| sales | `/api/sales/v1` | POS, invoices, sale orders, suspend, templates, returns, commission; sale saga |
| customers | `/api/customers/v1` | Customers, customer groups, credit, payments, statements |
| purchasing | `/api/purchasing/v1` | Suppliers, supplier groups, purchase requests, POs, receiving, supplier payments and returns |
| reports | `/api/reports/v1` | Read models built from events; dashboard and all reports |
| notification | `/api/notifications/v1` | Telegram daily report, alerts |
| document | `/api/documents/v1` | Receipts, A4 invoices, labels, PO and register PDFs |
| ai | `/api/ai/v1` | DeepSeek features: import cleanup, ask your data, summaries, substitutes, Rx parsing |

## Repo layout

```
pharmacy-system/
├── CLAUDE.md               # instructions for Claude Code
├── docker-compose.yml      # traefik, postgres, rabbitmq, redis + 14 services
├── traefik/                # static config + middlewares (headers, rate limits, forward auth)
├── infra/postgres/init/    # one database + one user per service
├── shared/                 # pharmacy_shared: config, db, errors, auth, outbox, logging
├── services/<name>/        # one FastAPI service each (app, migrations, tests, Dockerfile)
├── web/                    # front end (not started)
├── docs/                   # spec.md, ADRs, runbooks
├── scripts/test-all.sh
└── .github/workflows/ci.yml
```

## Building with Claude Code

Open this folder in VS Code, start Claude Code, and build one sprint at a time,
for example:

> Build sprint S0 "Setup" from docs/spec.md. First list what you will build and
> wait for my OK. Then build it, run `make test`, and tick S0 in CLAUDE.md.
