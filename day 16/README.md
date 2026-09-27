# Day 16 — MCP client → m365-mail

Минимальный MCP-клиент: поднимает ваш локальный сервер **m365-mail** по stdio,
устанавливает соединение и запрашивает список инструментов (`tools/list`).

Сервер почты не меняем — только подключаемся (база для следующих дней).

## Требования

- Node 20+
- Собранный [`MCP/mcp/m365-mail/dist/index.js`](../../MCP/mcp/m365-mail/dist/index.js)

Если `dist` нет:

```bash
cd "../../MCP/mcp/m365-mail"
npm install && npm run build
```

или из sources: `npm run sync-to-mcp`.

## Setup

```bash
cd "day 16"
cp .env.example .env   # при необходимости заполните M365_* как в .cursor/mcp.json
npm install
```

## CLI

```bash
npm start
```

Ожидание: `OK connected` и нумерованный список `m365_*` tools.

## UI

```bash
npm run ui
```

http://127.0.0.1:5015 — кнопка **Подключить и получить tools**.

## Как это работает

1. Клиент (`src/mcp_client.js`) спавнит `node …/m365-mail/dist/index.js`.
2. MCP handshake по stdio (`Client` + `StdioClientTransport`).
3. `listTools()` — Graph login не нужен.

Cursor MCP включать не обязательно: Day 16 сам запускает процесс.

## Files

| Path | Role |
|------|------|
| `src/mcp_client.js` | connect + listTools |
| `src/cli.js` | `npm start` |
| `src/app.js` | Express UI :5015 |
| `templates/index.html` | кнопка + таблица |

## Check

See [`example.md`](example.md).
