# Day 23 — example

## Ask (both)

```bash
curl -s http://127.0.0.1:5022/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Какие три компонента продуктивности выделяет автор?","mode":"both"}' | jq .
```

Enhanced response includes: `rewrite`, `pre_count`, `post_filter_count`, `sources`, `dropped`, rerank scores.

## Eval smoke

```bash
npm run eval -- --limit=2
```
