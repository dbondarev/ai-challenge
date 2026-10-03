# Day 21 — example

## 1. Env

```bash
cd "ai-challenge/day 21"
cp .env.example .env
# OPENAI_API_KEY=...
# BOOK_PATH points to Bailey txt under Books/
```

## 2. Build

```bash
npm install
npm run smoke    # quick DoD check
# or npm run build for full book
```

Expect:

- `data/index/fixed.json`
- `data/index/structure.json`
- `data/reports/comparison.md` with both strategies

## 3. UI

```bash
npm start
# http://127.0.0.1:5020
```

Open comparison table; search e.g. «медитация».

## 4. What to notice

- **fixed**: similar chunk lengths, `section` often nearest heading or body  
- **structure**: more unique `section` titles (Часть / chapter-like headings), variable sizes after sub-chunking  
