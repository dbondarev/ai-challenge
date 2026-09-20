# Day 12 — assistant personalization

Switch **user profiles** and compare dialog answers. No working / long-term memory layers — only profile + chat.

## Prompt

```text
[system] base role
[system] Active user profile: …   ← always
… dialog messages …
```

Switching profile clears the dialog so you can A/B the same question.

## Create profile

One text field → agent extracts `name`, `notes`, `preferences` (style, format, constraints, …).

Demo profiles: **Эрик Картман**, **Анна (B2B)**.

## Run

```bash
cd "day 12"
source .venv/bin/activate
flask --app app run --port 5011
```

Open http://127.0.0.1:5011

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/history` | Snapshot |
| `POST /api/chat` | Chat with active profile |
| `POST /api/profiles` | `{text}` create (LLM) or `{name, preferences}` |
| `POST /api/profiles/activate` | `{profile_id, clear_dialog?}` |
| `POST /api/profiles/delete` | `{profile_id}` |
| `POST /api/dialog/clear` | Clear chat only |

## Check

See [`example.md`](example.md).
