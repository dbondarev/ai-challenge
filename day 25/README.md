# Day 25 — Mini-chat with RAG + task memory

Production-like мини-чат поверх [Day 24](../day%2024/) grounded RAG:

- история диалога в session JSON
- каждый ход → RAG + источники
- **task memory**: goal, clarifications, constraints, terms

## Setup

```bash
cd "ai-challenge/day 25"
cp .env.example .env
npm install
npm start              # http://127.0.0.1:5024
```

## Scripts

| Script | Action |
|--------|--------|
| `npm start` | Web UI :5024 |
| `npm run chat` | CLI chat (`/new` `/state` `/quit`) |
| `npm run scenario` | 2×12 turns → `data/reports/scenarios.md` |

## API

- `POST /api/session` — new session
- `GET /api/session/:id`
- `DELETE /api/session/:id`
- `POST /api/chat` `{ session_id?, message }`
- `POST /api/scenario/run`
