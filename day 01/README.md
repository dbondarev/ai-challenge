# Day 01 — minimal OpenAI web chat

## Setup

```bash
cd "day 01"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` (already present) and set your key:

```
OPENAI_API_KEY=sk-...
```

Do not commit `.env` — it is gitignored at the repo root.

## Run

```bash
source .venv/bin/activate
flask --app app run
```

Open http://127.0.0.1:5000

## Models

| ID | Role |
|----|------|
| `gpt-5.4` | Default — balanced |
| `gpt-5.4-mini` | Cheaper / faster |
| `gpt-5.4-nano` | Cheapest |
| `gpt-5.5` | Flagship |
| `gpt-4o` | Legacy fallback |
