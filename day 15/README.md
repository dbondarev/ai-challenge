# Day 15 — controlled task transitions

Несколько задач + **строгие переходы**. UI без кнопок этапов: только сообщения.

## Graph

```text
planning → execution → validation → done
```

`planning → execution` только после явного утверждения плана в сообщении (`plan_approved=true`).  
Нет `force`. Пока `paused` — переходов нет.

## UI

1. Новая задача → planning (агент предлагает план).
2. Сообщениями: «План утверждаю» → «Начинай реализацию» → «на validation» → fail/pass → done / пауза.
3. Список задач справа; F5 восстанавливает `tasks.json`.

Нелегальный skip в тексте → отказ, FSM не двигается.

## Run

```bash
cd "day 15"
source .venv/bin/activate
flask --app app run --port 5014
```

http://127.0.0.1:5014

## Check

See [`example.md`](example.md). Кнопка **Автотест Day 15** гоняет сценарий сообщениями.
