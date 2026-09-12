# Day 10 — context strategies (no summary)

Three ways to control what goes into the model prompt: **Sliding Window**, **Sticky Facts**, and **Branching**. Full UI history can stay longer than the API window; no day-09 summary compression.

## Setup

```bash
cd "day 10"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
flask --app app run --port 5009
```

Open http://127.0.0.1:5009

## Strategies

| ID | API context |
|----|-------------|
| `sliding` | role + last `window_size` messages (default 8). Full transcript in `messages_full`. |
| `facts` | role + `Known facts` KV + last `facts_window` (default 6). Facts extracted after each user turn (`kind: facts_extract`). |
| `branching` | messages of the **active** branch only. Checkpoint → Fork → Switch. |

Token panel shows `prompt_estimate` for the active strategy and `prompt_estimate_if_full` (what you would send without window/facts truncation).

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/history` | Snapshot: strategy, messages, facts, branches, tokens |
| `POST /api/chat` | Chat + `strategy` / `window_size` / `facts_window` |
| `POST /api/reset` | Clear all strategy state |
| `POST /api/facts` | Save edited facts table |
| `POST /api/facts/refresh` | Force facts extract from last user message |
| `POST /api/checkpoint` | Mark checkpoint on active branch |
| `POST /api/branch` | Fork from checkpoint (`{ name }`) |
| `POST /api/branch/switch` | Switch active branch (`{ id }`) |

## Scenario ТЗ (compare strategies)

Same start prompt, then 10–15 turns. Reset between strategy runs (or use branches only for branching).

**Start:**

> Собираем ТЗ на лендинг: цель, аудитория, страницы, CTA, тон. Зафиксируй структуру и задай уточняющие вопросы по одному.

**Checklist (send one topic per turn):**

1. Цель: лиды на демо SaaS, не ecommerce
2. Аудитория: owners малого B2B SaaS в ЕС, 5–30 человек
3. Язык сайта: English
4. Тон: спокойный, без hype
5. Страницы: Home, Features, Pricing, About, Contact
6. Pricing: 3 тарифа + monthly/yearly toggle
7. CTA primary: Book a demo
8. CTA secondary: See pricing
9. Дизайн: светлый, много whitespace, без иллюстраций-стока
10. Срок: MVP за 4 недели
11. Ограничение: без личного кабинета в v1
12. Analytics: Plausible, не GA
13. Форма Contact: name, work email, company size
14. Проверка: «перечисли аудиторию, язык, страницы, CTA, analytics»
15. (опционально) Измени одно решение (например GA вместо Plausible) и снова спроси ранние детали

**Compare manually:**

| Strategy | Quality of recall | Detail stability | Tokens | UX |
|----------|-------------------|------------------|--------|----|
| sliding | | | | |
| facts | | | | |
| branching | | | | |

For branching: checkpoint after turn ~8, fork «Variant B», change Pricing, switch back to main and check that main still has the old Pricing.


## Compare page

Open http://127.0.0.1:5009/compare — one prompt is sent to all three strategies in parallel (3 API calls per turn). History is stored separately in `compare_history.json`.

| Column | API context |
|--------|-------------|
| Sliding | last `window_size` |
| Facts | sticky facts + last `facts_window` |
| Branching | full track messages (no window) |
