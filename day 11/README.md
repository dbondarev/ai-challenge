# Day 11 — agent memory layers

Three memory layers. **Keys are never chosen by the user** — the agent extracts facts and stores them.

## Layers

| Layer | Storage | Lifetime | User action |
|-------|---------|----------|-------------|
| **Dialog** (short-term) | RAM only | Gone on page refresh / «Очистить диалог» | Chat normally |
| **Task** (working) | `working.json` | Cleared by «Новая задача» | On a user message: «→ память задачи» |
| **Long-term** | `long_term.json` | Until deleted | On a user message: «→ долговременная»; each fact has **удалить** |

Task title is set by the agent when facts are saved into working memory and shown in the UI.

### Prompt composition

```text
[system] role
[system] Long-term memory: …
[system] Working memory (current task: <title>): …
… last window_size dialog messages …
```

## UI

1. Dialog on top — each **user** bubble has two buttons (task / long-term).
2. Below: two panels — facts in task memory and facts in long-term.

## Setup

```bash
cd "day 11"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set OPENAI_API_KEY
```

## Run

```bash
source .venv/bin/activate
flask --app app run --port 5010
```

Open http://127.0.0.1:5010

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/history?boot=1` | Snapshot; `boot=1` clears dialog |
| `POST /api/chat` | Message → dialog only → reply |
| `POST /api/memory/remember` | `{layer: working\|long_term, text\|index}` — LLM picks keys |
| `POST /api/memory/delete` | `{layer: long_term\|working, key}` |
| `POST /api/memory/clear` | `{layer: short\|working\|long_term\|all}` — `working` = new task (also clears dialog) |
| `POST /api/reset` | Clear all layers |

## Check impact

See [`example.md`](example.md).
