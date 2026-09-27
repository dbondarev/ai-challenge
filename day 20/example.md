# Day 20 — example

## 1. Token

Singularity → Account → API Access → create token → put in `day 20/.env` as `SINGULARITY_ACCESS_TOKEN` (or `SINGULARITY_TOKEN`).

Default transport `native` uses ModumUpCloud `singularity-mcp-server-2.1.1/run-mcp.sh`.

## 2. Start UI

```bash
cd "ai-challenge/day 20"
npm start
# http://127.0.0.1:5019
```

Status should show both `m365` and `singularity` tool counts > 0.

## 3. Cross-server flow

Click **Preset: mail → задача** or send:

> Найди в почте письма про invoice и создай в Singularity задачу `[Day20] …`

Expected trace order (typical):

1. `m365` / `m365_search_messages` (or similar)
2. optional read/list
3. `singularity` / create-task tool (`singularity_create_task` on stdio proxy, or official tasks tool)

## 4. Smoke CLI

```bash
npm run smoke
```

Prints tool counts, reply, ordered trace, `cross_server: true`.
