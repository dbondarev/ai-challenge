import { embedQuery } from "./embed.js";
import { loadIndex, resolveDocId } from "./index_store.js";

export function cosine(a, b) {
  let dot = 0;
  let na = 0;
  let nb = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  const d = Math.sqrt(na) * Math.sqrt(nb);
  return d ? dot / d : 0;
}

export async function searchIndex(strategy, query, topK = 5, docId) {
  const id = resolveDocId(docId);
  if (!id) {
    throw new Error("No active document. Select a document and Build first.");
  }
  const idx = loadIndex(id, strategy);
  if (!idx?.chunks?.length) {
    throw new Error(
      `Index not found for doc=${id} strategy=${strategy}. Run Build.`
    );
  }
  const q = await embedQuery(query);
  const scored = [];
  for (const c of idx.chunks) {
    if (!c.embedding?.length) continue;
    scored.push({
      score: cosine(q, c.embedding),
      chunk_id: c.chunk_id,
      section: c.section,
      source: c.source,
      title: c.title,
      text_preview: String(c.text || "").slice(0, 320),
      char_start: c.char_start,
      char_end: c.char_end,
    });
  }
  scored.sort((x, y) => y.score - x.score);
  return {
    doc_id: id,
    strategy,
    query,
    results: scored.slice(0, topK),
  };
}
