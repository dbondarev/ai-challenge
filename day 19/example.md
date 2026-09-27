# Day 19 — example run

## 1. Start UI

```bash
cd "ai-challenge/day 19"
npm start
# open http://127.0.0.1:5018
```

Status panel should show openai + m365 script path + `data/out`.

## 2. Pipeline: day summary

Click **Пайплайн: сводка за день**.

Expected step trace:

1. `compose_list_day` — count of messages  
2. `compose_summarize` — Russian summary preview  
3. `compose_save` — absolute path under `data/out/`

Open the saved `.md` file; summary should be non-empty.

## 3. Pipeline: search

Enter a query (e.g. a known sender or keyword), click **Пайплайн: поиск**.

Same 3-step chain; step 1 is `compose_search`.

## 4. Rules demo

**Показать rules** → JSON of inbox messageRules.

Optional create: load folders → fill displayName / senderContains / folder → check confirm → create.

## 5. Agent

Preset **Сводка за день + сохранить** should prefer a single `compose_pipeline` call (see toolTrace).

## 6. Compose MCP smoke

```bash
# In another terminal / Cursor MCP config pointing at:
# node "/…/ai-challenge/day 19/src/mcp_compose_server.js"
npm run mcp
```

Call `compose_pipeline` with `{ "mode": "day" }` from an MCP client.
