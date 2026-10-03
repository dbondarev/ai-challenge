# Day 22 — First RAG query

RAG поверх индекса [Day 21](../day%2021/): вопрос ? поиск чанков ? LLM. Сравнение с ответом **без RAG**.

## Pipeline

1. Active document from Day 21 catalog  
2. Embed question ? cosine top-K (`structure` by default)  
3. Prompt with cited context ? OpenAI chat  
4. Parallel **no_rag** answer for comparison  

## Setup

```bash
cd "ai-challenge/day 22"
cp .env.example .env   # OPENAI_API_KEY (or reuse from day 21)
# Ensure Day 21 has an active built index
npm install
npm start              # http://127.0.0.1:5021
```

## Scripts

| Script | Action |
|--------|--------|
| `npm start` | UI :5021 |
| `npm run eval` | Run 10 control questions ? `data/reports/eval.md` |

## Eval set

10 questions in `src/eval_set.js` with `expect`, `expected_sections`, keywords. Includes one out-of-corpus negative control.

## API

- `GET /api/status`
- `POST /api/ask` `{ question, mode: "rag"|"no_rag"|"both" }`
- `GET /api/eval/set`
- `POST /api/eval/run` `{ limit? }`
