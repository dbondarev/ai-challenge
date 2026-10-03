# Day 25 — example

```bash
# new session + chat
SID=$(curl -s -X POST http://127.0.0.1:5024/api/session | jq -r .session_id)
curl -s http://127.0.0.1:5024/api/chat \
  -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"$SID\",\"message\":\"Какие три компонента продуктивности?\"}" | jq .
```

```bash
npm run scenario
```
