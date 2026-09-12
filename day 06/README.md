# Day 06 — first agent

A separate `Agent` entity owns the LLM request/response. Flask only wires the web UI to `Agent.reply()`.

## Layout

| File | Role |
|------|------|
| `agent.py` | `Agent` class: OpenAI client + `reply()` |
| `app.py` | Thin HTTP layer — no direct `OpenAI(...)` calls |
| `templates/index.html` | Minimal chat UI |

## Setup

```bash
cd "day 06"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in `.env` (gitignored).

## Run

```bash
source .venv/bin/activate
flask --app app run --port 5005
```

Open http://127.0.0.1:5005
