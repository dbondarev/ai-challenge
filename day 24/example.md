# Day 24 — example

```bash
curl -s http://127.0.0.1:5023/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Какие три компонента продуктивности выделяет автор?"}' | jq .
```

Expect fields: `answer`, `refuse`, `sources[]`, `quotes[]`, `retrieval_meta`, `validation`.

```bash
npm run eval -- --limit=2
```
