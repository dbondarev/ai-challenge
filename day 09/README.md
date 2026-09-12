# Day 09 — history compression (split compare)

One user prompt is sent to **two parallel tracks**:

| Left | Right |
|------|-------|
| Full history | Role + **summary** + last `keep_last` messages |

Each track gets its own assistant reply. Token stats for both sit above the dialog. Expand **Запрос в API** under each column to see the exact messages array sent to the model.

## Setup

```bash
cd "day 09"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
flask --app app run --port 5008
```

Open http://127.0.0.1:5008

## How compression works (right column)

1. `system` role
2. `system` summary (if any)
3. last `keep_last` messages from the compressed track

Defaults: `keep_last=6`, `summarize_every=10`. Auto-summarize runs on the compressed track after chat turns. **Сжать сейчас** forces a summary from the compressed history.

## Compare quality / tokens

1. Send «Факт в начале» (ALTAIR-42).
2. Add several long turns.
3. Click **Сжать сейчас** (or wait for auto threshold).
4. Ask about the early fact on the next turn — compare left vs right answers and prompt token estimates.
