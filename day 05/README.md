# Day 05 — model tiers (weak / medium / strong)

Same prompt on three OpenAI models. Measure latency, tokens, and estimated cost.

We stay on OpenAI (same stack as days 1–4). HuggingFace in the assignment brief is only an example of "weak → mid → strong".

## Setup

```bash
cd "day 05"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in `.env` (gitignored).

## Run

```bash
source .venv/bin/activate
flask --app app run --port 5004
```

Open http://127.0.0.1:5004

## Tiers

| Tier | Model | USD / 1M tokens (in / out, approx.) |
|------|-------|-------------------------------------|
| weak | `gpt-5.4-nano` | 0.20 / 1.25 |
| medium | `gpt-5.4-mini` | 0.75 / 4.50 |
| strong | `gpt-5.5` | 5.00 / 30.00 |

All calls use `temperature=0`.

## Cost estimate

```
cost_usd ≈ prompt_tokens/1e6 * input_price + completion_tokens/1e6 * output_price
```

Prices are hardcoded from the public list — verify against the official pages:

- https://platform.openai.com/docs/pricing
- https://platform.openai.com/docs/models

Comparison notes stay in browser `localStorage` only.
