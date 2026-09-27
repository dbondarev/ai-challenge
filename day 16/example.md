# Day 16 — проверка

## CLI

```bash
cd "day 16"
npm install
npm start
```

Ожидаемый фрагмент вывода:

```text
OK connected
Tools: 10

1. m365_connection_status
   Returns whether Microsoft 365 is connected…
2. m365_start_login
   …
3. m365_list_mailbox_targets
…
10. m365_create_message_rule
```

(Точное число tools зависит от версии m365-mail; важно: соединение OK и имена `m365_*`.)

## UI

```bash
npm run ui
```

1. http://127.0.0.1:5015
2. **Подключить и получить tools**
3. Статус `OK connected`, таблица с теми же tools

## Если FAILED

- Нет `MCP/mcp/m365-mail/dist/index.js` — соберите mail MCP (см. README).
- Неверный `MCP_SERVER_ARGS` в `.env` — укажите абсолютный путь к `dist/index.js`.
