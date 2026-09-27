# Day 19 — MCP tool composition (mail)

Compose MCP tools on top of `m365-mail`: **fetch → summarize → save**, with a UI step trace on port **5018**.

## What it does

| Layer | Role |
|-------|------|
| `m365-mail` (existing) | `m365_list_recent_messages`, `m365_search_messages`, rules |
| Day 19 compose server | `compose_*` wrappers + **`compose_pipeline`** (auto chain) |
| Express UI `:5018` | Pipeline buttons, rules demo, optional chat agent |

Pipeline does **not** use an LLM between steps: fetch JSON → summarize → write `data/out/*.md`.

## Tools (`npm run mcp`)

| Tool | Behavior |
|------|----------|
| `compose_list_day` | → `m365_list_recent_messages` |
| `compose_search` | → `m365_search_messages` |
| `compose_summarize` | OpenAI RU summary (template fallback) |
| `compose_save` | write `data/out/{file}.md` |
| `compose_pipeline` | day \| search → summarize → save |
| `compose_list_rules` | → `m365_list_message_rules` |
| `compose_create_rule` | → `m365_create_message_rule` |

## Setup

```bash
cd "ai-challenge/day 19"
cp .env.example .env   # fill OPENAI_* and M365_*
npm install
npm start              # http://127.0.0.1:5018
```

Compose MCP (stdio) for Cursor / other clients:

```bash
npm run mcp
```

## HTTP API

- `GET /api/status`
- `POST /api/pipeline` `{ mode: "day"|"search", query?, hours?, top? }`
- `POST /api/rules/list`
- `POST /api/rules/create` `{ confirm: true, displayName, senderContains, moveToFolder, sequence? }`
- `GET /api/folders`
- `POST /api/chat` `{ message, history? }`

## DoD checklist

1. Pipeline day → 3 steps in UI + file in `data/out/` + non-empty summary  
2. Pipeline search with query works the same  
3. Rules list shows; create only with confirm  
4. `npm run mcp` exposes the same compose tools  

See [example.md](./example.md).
