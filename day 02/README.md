# Day 02 — response control (prompt + API)

Same user prompt, two Chat Completions calls: unconstrained vs controlled.

## Setup

```bash
cd "day 02"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in `.env` (copied from day 01; gitignored).

## Run

```bash
source .venv/bin/activate
flask --app app run --port 5001
```

Open http://127.0.0.1:5001

(Use port 5001 if day 01 still runs on 5000.)

## Field map

| UI field | Goes to | Role in the exercise |
|---------|---------|----------------------|
| Prompt | user message (A and B) | Same request |
| Format | system (B) | Explicit response format |
| Soft length checkbox | system (B) | Soft length instruction |
| Soft stop checkbox | system (B) | Soft stop instruction |
| `max_completion_tokens` | API (B) | Hard length limit |
| `stop` (`|` separated, up to 4) | API (B) | Hard stop sequences |
| `response_format` | API (B) | `text` or `json_object` |
| `temperature` | API (B) | Extra control knob |

## Compare flow

`POST /api/compare` returns:

- `unconstrained` — prompt only + `finish_reason` / usage
- `controlled` — system + API kwargs + `request_echo` of what was sent
