# Day 04 — temperature comparison

Same prompt at `temperature` **0**, **0.7**, and **1.2**. Compare accuracy, creativity, and diversity.

## Setup

```bash
cd "day 04"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in `.env` (gitignored).

## Run

```bash
source .venv/bin/activate
flask --app app run --port 5003
```

Open http://127.0.0.1:5003

## Why multiple samples

By default the UI asks for **2 samples per temperature** (6 API calls). One sample cannot show diversity within the same setting.

## When to use which temperature

| Temp | Typical fit |
|------|-------------|
| `0` | Facts, extraction, code, reproducible answers |
| `0.7` | General chat / balanced writing |
| `1.2` | Brainstorming, names, creative variants (higher variance) |

Conclusions notes stay in browser `localStorage` only.
