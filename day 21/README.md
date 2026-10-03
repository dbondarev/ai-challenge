# Day 21 — Document indexing

Индексация книги Криса Бэйли («Мой продуктивный год») с двумя стратегиями chunking, OpenAI embeddings и локальным JSON-индексом.

## Source

`BOOK_PATH` → `Books/Byeyili_K._Moyi_Produktivnyiyi_God_K.txt` (Windows-1251, только чтение; файл **не** копируется в репозиторий).

## Pipeline

1. Load + decode cp1251 → UTF-8 in memory  
2. Chunk **fixed** (size/overlap) and **structure** (Часть / headings → sub-chunks)  
3. Embed (`text-embedding-3-small`)  
4. Save `data/index/{fixed,structure}.json` with metadata  
5. Write `data/reports/comparison.md`

## Metadata per chunk

`chunk_id`, `strategy`, `source`, `title`, `section`, `chunk_index`, `char_start`, `char_end`, `text`, `embedding`

## Multi-document

- Browse `Books/` or `data/inbox/`, paste a path, or upload `.txt`/`.md`
- **Build** indexes that document (both strategies) and registers it in `data/index/catalog.json`
- Switch active document in the list → compare/search use the active one
- Indexes live under `data/index/{docId}/fixed.json` + `structure.json`

## Setup

```bash
cd "ai-challenge/day 21"
cp .env.example .env   # set OPENAI_API_KEY
npm install
npm run build          # full book (API cost)
# or
npm run smoke          # first ~60k chars, ≤40 chunks/strategy
npm start              # http://127.0.0.1:5020
```

## UI

- Build / smoke build  
- Comparison table  
- Sample chunks with metadata  
- Cosine search top-5 per strategy  

## Scripts

| Script | Action |
|--------|--------|
| `npm run build` | Full index both strategies |
| `npm run smoke` | Fast capped build |
| `npm run compare` | Rebuild comparison report from existing indexes |
| `npm start` | UI :5020 |
