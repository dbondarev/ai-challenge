# Day 18 — Mail digest scheduler + Telegram

Долгоживущий агент: раз в сутки в **06:00 America/Chicago** (Austin) собирает почту через MCP **m365-mail**, делает сводку, сохраняет в JSON и шлёт в Telegram.

Для демо — та же джоба по кнопке **Run now**.

## MCP

### Mail (существующий сервер)

Новый tool в m365-mail: **`m365_list_recent_messages`** (`hours`, `top`) — см. `MCP/mcp/m365-mail/src/index.ts`.

### Digest tools (этот процесс)

| Tool / API | Назначение |
|------------|------------|
| `digest_run_now` | Немедленный прогон (`POST /api/digest/run` или `npm run mcp`) |
| `digest_get_last` | Последняя сводка из JSON |

Stdio MCP: `npm run mcp` (для Cursor). Cron живёт только при `npm start`.

## Setup

1. Пересобрать mail MCP (если ещё не): `cd MCP/mcp/m365-mail && npm run build`
2. M365 уже залогинен (токены в `~/.modumup-m365-mail-mcp/`)
3. Telegram:
   - создать бота у [@BotFather](https://t.me/BotFather) → `TELEGRAM_BOT_TOKEN`
   - написать боту /start, узнать `chat_id` (@userinfobot или `getUpdates`) → `TELEGRAM_CHAT_ID`
4. Env:

```bash
cd "day 18"
cp .env.example .env
# OPENAI_API_KEY, M365_*, TELEGRAM_*
npm install
npm start
```

http://127.0.0.1:5017

Без Telegram credentials digest всё равно сохранится в `data/digests.json` (`telegram.skipped`).

## Держать 24/7

Оставить `npm start` запущенным локально, либо позже launchd/systemd/VPS (не входит в задание).

## Check

See [`example.md`](example.md).
