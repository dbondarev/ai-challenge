# Day 17 — Agent + first MCP tool call

OpenAI-агент вызывает инструменты MCP-сервера **m365-mail** по stdio и использует результат в ответе.

MCP-сервер уже реализован: регистрация, параметры, результат — в
[`MCP/mcp/m365-mail/src/index.ts`](../../MCP/mcp/m365-mail/src/index.ts) (`registerTool`).
Day 17 подключает его к агенту и делает `tools/call`.

Демо-инструмент: **`m365_connection_status`** (всегда возвращает JSON; Graph login не обязателен для успешного MCP round-trip).

## Setup

```bash
cd "day 17"
cp .env.example .env   # OPENAI_API_KEY + M365_* как в Day 16 / .cursor/mcp.json
npm install
npm start
```

http://127.0.0.1:5016

Нужен собранный `MCP/mcp/m365-mail/dist/index.js` (см. Day 16 README).

## Как работает

1. UI → `POST /api/chat`
2. Агент открывает MCP session, `listTools`
3. OpenAI tool-calling → `mcp.callTool(name, args)`
4. Второй ход модели с результатом tool → ответ пользователю
5. UI показывает reply + блок **MCP tool call**

## Если status = not_connected

Войдите один раз через Cursor MCP (`m365_start_login`) или любой клиент m365-mail.
Токены: `~/.modumup-m365-mail-mcp/`. Для задания достаточно увидеть сам call и JSON result.

## Check

See [`example.md`](example.md).
