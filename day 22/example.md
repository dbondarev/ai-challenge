# Day 22 — example

## 1. Index (Day 21)

```bash
cd "../day 21"
npm start   # build/select a document if needed
```

Prefer a full `npm run build` (not only smoke) for better eval coverage.

## 2. Start RAG UI

```bash
cd "../day 22"
npm install
npm start
# http://127.0.0.1:5021
```

## 3. Compare modes

Ask: «Какие три компонента продуктивности выделяет автор?»

- **Оба режима** ? left: RAG with sources `[1]…`; right: general knowledge  
- Click a control question from the list to fill the box  

## 4. Eval

```bash
npm run eval
# or UI: «Прогнать набор» / smoke 2 questions
```

Opens `data/reports/eval.md` with side-by-side previews and heuristic scores.
