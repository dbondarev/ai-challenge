# Day 07 — conversation memory

The `Agent` keeps dialog `messages` in `history.json` and reloads them on startup, so the chat continues after a Flask restart.

## Setup

```bash
cd "day 07"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in `.env` (gitignored). `history.json` is also gitignored.

## Run

```bash
source .venv/bin/activate
flask --app app run --port 5006
```

Open http://127.0.0.1:5006

## How memory works

1. Each turn appends `user` + `assistant` to in-memory history and writes `history.json`.
2. On process start, `Agent` loads that file.
3. UI calls `GET /api/history` on page load to redraw the thread.
4. `POST /api/reset` clears the file.

## Manual check

1. Tell the agent your name (or another fact) in 2–3 messages.
2. Stop Flask (`Ctrl+C`) and start it again on port 5006.
3. Ask what your name is — it should remember; the thread should already be on screen.
