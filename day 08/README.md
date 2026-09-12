# Day 08 — token counting

Counts tokens for the current request, dialog history, and model reply. Uses `tiktoken` estimates plus authoritative `usage` from the API. Overflow checks against the **real model context window**.

## Setup

```bash
cd "day 08"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in `.env`. `history.json` is gitignored.

## Run

```bash
source .venv/bin/activate
flask --app app run --port 5007
```

Open http://127.0.0.1:5007

## Model context windows

| Model | Context window |
|-------|----------------|
| gpt-5.4 / gpt-5.5 | 1,050,000 |
| gpt-5.4-mini / gpt-5.4-nano | 400,000 |
| gpt-4o | 128,000 |

If `prompt_estimate` exceeds the selected model's window, the agent does **not** call the API, rolls back the user turn, and returns `context overflow`.

## What is counted

| Metric | Source |
|--------|--------|
| request_estimate | tiktoken on the new user message |
| history_estimate | tiktoken on system + stored messages |
| prompt_estimate | tiktoken on the full API messages array |
| prompt/completion/total | `usage` from Chat Completions |
| reply_estimate | tiktoken on assistant text |
| remaining_estimate | model window − prompt_estimate |
| cost_usd | estimate from public $/1M prices |

## Presets in the UI

1. **Короткий** — small message
2. **Длинный** — longer filler text (watch prompt tokens grow)
3. **Очень длинный** — much larger filler (still usually far below real windows)

## Pricing note

Costs are approximate list prices. Verify: https://platform.openai.com/docs/pricing
