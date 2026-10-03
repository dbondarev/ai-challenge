# Day 24 — Citations, sources, anti-hallucination

Grounded RAG поверх [Day 23](../day%2023/) pipeline (rewrite → filter → rerank) и индекса [Day 21](../day%2021/).

Обязательный структурированный ответ: **answer + sources + quotes**.  
При слабой релевантности (`KNOW_MIN_SCORE`) или fallback фильтра — режим **«не знаю»**.

## Pipeline

1. Day 23 enhanced retrieve → top `K_POST`  
2. Gate: max cosine ≥ `KNOW_MIN_SCORE` (default 0.38), не fallback  
3. LLM → JSON `{ refuse, answer, sources, quotes }`  
4. Validate: цитаты — подстроки чанков; иначе force refuse  

## Setup

```bash
cd "ai-challenge/day 24"
cp .env.example .env
npm install
npm start              # http://127.0.0.1:5023
```

## Scripts

| Script | Action |
|--------|--------|
| `npm start` | UI :5023 |
| `npm run eval` | 10 Q checks → `data/reports/eval.md` |

## API

- `GET /api/status`
- `POST /api/ask` `{ question }`
- `GET /api/eval/set`
- `POST /api/eval/run` `{ limit? }`
