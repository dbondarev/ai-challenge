# Day 03 — reasoning modes

One task, four ways through the OpenAI API. Compare answers and accuracy.

## Setup

```bash
cd "day 03"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in `.env` (gitignored).

## Run

```bash
source .venv/bin/activate
flask --app app run --port 5002
```

Open http://127.0.0.1:5002

## Modes

| ID | Method | API shape |
|----|--------|-----------|
| `direct` | Direct answer | user = task only |
| `step_by_step` | "Solve step by step" | system instruction + user task |
| `meta_prompt` | Prompt then solve | step1 generate prompt; step2 run it as user |
| `experts` | Expert panel | system with roles (default: аналитик, инженер, критик) |

Default task is the river crossing puzzle (farmer / wolf / goat / cabbage) so you can judge correctness against a known solution.

Comparison notes in the UI stay in `localStorage` only.
