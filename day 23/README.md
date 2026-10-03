# Day 23 — Reranking and filtering

Enhanced RAG поверх [Day 21](../day%2021/) index и [Day 22](../day%2022/) eval set:
**query rewrite → retrieve K_pre → similarity threshold → LLM rerank → K_post → answer**.

Сравнение с **baseline** (как Day 22: raw question → top-K → answer).

## Pipeline (enhanced)

1. LLM rewrite — короткий поисковый запрос на русском  
2. Retrieve `K_PRE` (default 12) по rewritten query (`structure`)  
3. Filter: отбросить чанки с `score < SIM_THRESHOLD` (default 0.32); fallback top-1  
4. LLM rerank: scores 0–10 к *исходному* вопросу; tie-break cosine  
5. Top `K_POST` (default 5) → ответ с цитатами `[n]`

## Setup

```bash
cd "ai-challenge/day 23"
cp .env.example .env   # OPENAI_API_KEY (или из day 21/22)
# Active Day 21 index обязателен
npm install
npm start              # http://127.0.0.1:5022
```

## Env

| Variable | Default |
|----------|---------|
| `PORT` | 5022 |
| `K_PRE` | 12 |
| `K_POST` | 5 |
| `SIM_THRESHOLD` | 0.32 |
| `RAG_STRATEGY` | structure |
| `DAY21_ROOT` | ../day 21 |
| `DAY22_ROOT` | ../day 22 |

## Scripts

| Script | Action |
|--------|--------|
| `npm start` | UI :5022 |
| `npm run eval` | Baseline vs enhanced → `data/reports/eval.md` |

## API

- `GET /api/status` — active doc, K_PRE/K_POST/threshold
- `POST /api/ask` `{ question, mode: "baseline"|"enhanced"|"both" }`
- `GET /api/eval/set` — Day 22 questions
- `POST /api/eval/run` `{ limit? }`

## DoD

1. Enhanced pipeline: rewrite + threshold + topK pre/post + LLM rerank  
2. UI: baseline vs enhanced + intermediate stats  
3. `npm run eval` пишет сравнение  
4. Индекс только из Day 21 (без дублирования)
