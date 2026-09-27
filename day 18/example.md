# Day 18 — проверка (для видео)

## Подготовка

```bash
cd "day 18"
npm install
npm start
```

Открыть http://127.0.0.1:5017  
В статусе: cron `0 6 * * *` America/Chicago, telegram ok (если заполнен `.env`).

## Сценарий демо

1. Нажать **Run now**.
2. Дождаться сводки: `mail_count`, текст summary.
3. Проверить Telegram — пришло то же сообщение.
4. В истории — строка `trigger=manual`.
5. Упомянуть: ночью/утром то же самое сделает cron в **06:00 Austin**.

## MCP (опционально)

```bash
npm run mcp
```

Инструменты: `digest_run_now`, `digest_get_last`, `digest_list`.
