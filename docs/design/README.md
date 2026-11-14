# Design handoff (Claude Design)

Source: Claude Design project `57f26050-e206-4736-9562-b5964edab53c`
(https://claude.ai/design/p/57f26050-e206-4736-9562-b5964edab53c), imported 01/11/2026. The whole project is copied
byte for byte into `project/` (39 files; the project's `.thumbnail` preview image is not included). This folder is the
visual source of truth for the web front end (`web/`). For behaviour, `docs/spec.md` and the API win.

## What is here

| Path | What |
| --- | --- |
| `tokens.json` | Design tokens: colours (primary, neutral, semantic, reserved safety badges, status pills, POS dark), fonts, type scale with Khmer line heights, spacing, radii, shadows, sizes, breakpoints, usage rules. `web/` builds its Tailwind theme from this file. |
| `error-messages.json` | The 13 error codes the design maps to friendly English + Khmer messages, with severity. |
| `screens.md` | Every frame (152): file, frame id, name (Group / Screen / Device / Language), roles, and the API tag the designer wrote. |
| `project/Design System.dc.html` | Foundations and components: colour, type, spacing/grid, controls, data table, dialogs (PIN pad, witness, confirm with reason), feedback, status pills, safety badges, charts, shell, flows, error code map. |
| `project/App Shell.dc.html` | 2a–2f: sidebar (expanded / collapsed), header (branch switcher, Ctrl K, KM/EN, bell, user menu), role-filtered menu, cost hidden, mobile tabs + More. |
| `project/Auth.dc.html` | 15a–15j: login (KM/EN, mobile), wrong password, 2FA code / setup, forced 2FA, account locked, set PIN. |
| `project/Shared States.dc.html` | 16a–16j: empty, skeleton, server error, offline, 403, 404, PIN locked, session expired, toasts, field errors. |
| `project/POS.dc.html`, `POS Lite.dc.html`, `POS Back Office.dc.html` | 3a–3o (the 9 POS flows, desktop), 4a–4e (phone + tablet), 12a–12n (templates, suspended, sale order, list sale, invoice, return, commission, promotion editor, dispense from Rx, PO create, transfer request, suppliers, medicine detail). |
| `project/Prescriptions.dc.html`, `Controlled Drugs.dc.html` | 6a–6h, 7a–7f. |
| `project/Stock.dc.html`, `Warehouse.dc.html` | 8a–8i (incl. mobile blind count + second count), 9a–9g. |
| `project/Purchase.dc.html`, `Transfer.dc.html` | 10a–10f (incl. mobile receiving), 11a–11g (incl. mobile receive by QR). |
| `project/Contacts.dc.html` | 12a–12d (customer groups, customers, customer detail, supplier detail). |
| `project/Dashboard.dc.html`, `Reports.dc.html` | 5a–5d, 13a–13p (one report template, 16 examples, cost-hidden variant). |
| `project/Users and Settings.dc.html` | 14a–14i. |
| `project/Print Layouts.dc.html` | 17a–17i (receipts, labels, A4 invoice, sale order, PO, PO group, transfer note, customer statement). |
| `project/API Coverage Screens.dc.html` | 18a–18h and 15k: screens added after the designer's API audit. |
| `project/ui-audit.md`, `api-audit.md`, `api-inventory.md` | The designer's coverage table, API audit and (older) UI → API list. |
| `project/uploads/ui-design-prompt.md` | The brief the design was made from. |
| `project/uploads/spec-*.json` | The 14 OpenAPI documents the designer used: a snapshot from before S8b. The current ones come from `make openapi`. |
| `project/S8b-plan.md` | The S8b plan as uploaded to the design project (S8b is built; `docs/spec.md` has what was made). |
| `project/support.js` | The Claude Design runtime the `.dc.html` files load. |

## Reading the `.dc.html` files

Each file is a template (`<x-dc>…</x-dc>`) plus a script whose `renderVals()` builds the frames' sample data. The
script holds the exact strings (English and Khmer), sample rows, colours and widths. Open them in Claude Design to see
them rendered. Opened locally, they need `support.js` next to them and React on the page.

## Notes for the build

- **API tags are from design time.** Some name endpoints that never existed, such as `/api/stock/v1/...` and
  `/api/rx/v1/...` in `api-inventory.md`. The real endpoint for each screen is the one its page in `web/src/features/` calls.
- **"⚠ API pending" is out of date.** The ten items marked "API pending" in `api-audit.md` were built in S8b:
  - KHQR;
  - promotion preview;
  - price history;
  - register entry detail;
  - recall;
  - supplier return;
  - customer statement PDF;
  - sessions;
  - exchange-rate history;
  - 2FA backup codes.
- **Some designed details have no data in the API.** Where that happens the screen hides the detail, and the plan
  lists it under "missing" or "design vs API". The screen never shows invented values.
- **Sample data is for the design only.** The branches, staff names and numbers in the frames are sample content. The
  front end shows only API data.
