# Day 14 — invariants and hard constraints

The assistant must not violate **invariants** stored separately from the dialog.

## What is an invariant

| Category | Examples |
|----------|----------|
| `architecture` | Monolith Flask API + one SPA in v1; no microservices |
| `tech_decision` | Auth = session/cookie only; no JWT in v1 |
| `stack` | Vue 3 + TypeScript frontend; Python/Flask backend |
| `business_rule` | Kyle ≤ 20% profit; Cheesy Poofs price ≥ $2 |

Stored in `invariants.json`. Chat never auto-writes there. Inactive items are omitted from the prompt.

## Prompt assembly

```text
[system] role
[system] INVARIANTS (must not violate):
  - [stack] (stack-frontend) …
  Rules: check every active invariant; on conflict REFUSE and explain; no workarounds.
… dialog …
```

Clearing the dialog does **not** clear invariants.

## Setup

```bash
cd "day 14"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
flask --app app run --port 5013
```

Open http://127.0.0.1:5013

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/history` | messages + invariants + tokens + last payload |
| `POST /api/chat` | chat with invariants injected |
| `GET /api/invariants` | list |
| `POST /api/invariants` | upsert `{id?, category, statement, active}` |
| `POST /api/invariants/toggle` | `{id, active}` |
| `POST /api/invariants/delete` | `{id}` |
| `POST /api/invariants/reset-demo` | restore demo set |
| `POST /api/dialog/clear` | dialog only |
| `POST /api/reset` | clear dialog (invariants kept) |

## Check

See [`example.md`](example.md): conflict presets (React / JWT / Kyle 35%) should be refused with an explanation; Vue structure request should be answered.
