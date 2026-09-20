# Day 13 — Task State Machine (multi-task)

Несколько задач с этапами FSM. История и статусы живут в `tasks.json` и поднимаются при обновлении страницы.

## Этапы

```text
planning → execution → validation → done
```

Пауза ортогональна этапу. Rework: `validation → execution`, `execution → planning`.

## UI

1. **Новая задача** — текст → агент стартует в `planning` и просит подтверждение.
2. Кнопки: следующий этап, переход на другой разрешённый, **Пауза** / **Продолжить**, комментарий к этапу.
3. Справа — список задач и текущий этап; клик переключает задачу с её диалогом.

## Run

```bash
cd "day 13"
source .venv/bin/activate
flask --app app run --port 5012
```

http://127.0.0.1:5012

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/history` | Все задачи + активная + сообщения |
| `POST /api/task/create` | `{text}` — новая задача |
| `POST /api/task/select` | `{task_id}` |
| `POST /api/task/delete` | `{task_id}` |
| `POST /api/task/advance` | Следующий этап + ответ агента |
| `POST /api/task/transition` | `{stage}` |
| `POST /api/task/pause` | `{reason?}` |
| `POST /api/task/resume` | Снять паузу |
| `POST /api/task/comment` | `{text}` — комментарий к этапу |

## Check

See [`example.md`](example.md).
