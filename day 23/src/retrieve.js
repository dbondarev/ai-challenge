import { day21 } from "./bridge.js";

const CHUNK_PROMPT_CAP = 1200;

/**
 * Retrieve top-K chunks with full text from Day 21 index.
 */
export async function retrieve({ question, docId, strategy, topK } = {}) {
  const d21 = await day21();
  const strat = (
    strategy ||
    process.env.RAG_STRATEGY ||
    "structure"
  ).trim();
  const k = Number(topK || process.env.K_PRE || process.env.RAG_TOP_K || 12);
  const id = d21.index_store.resolveDocId(docId);
  if (!id) {
    throw new Error("No active Day 21 document. Build/select an index in Day 21.");
  }
  const idx = d21.index_store.loadIndex(id, strat);
  if (!idx?.chunks?.length) {
    throw new Error(`No index for doc=${id} strategy=${strat}`);
  }

  const qEmb = await d21.embed.embedQuery(question);
  const scored = [];
  for (const c of idx.chunks) {
    if (!c.embedding?.length) continue;
    scored.push({
      score: d21.search.cosine(qEmb, c.embedding),
      chunk_id: c.chunk_id,
      section: c.section,
      source: c.source,
      title: c.title,
      text: String(c.text || ""),
      char_start: c.char_start,
      char_end: c.char_end,
    });
  }
  scored.sort((a, b) => b.score - a.score);
  const results = scored.slice(0, k).map((r) => ({
    ...r,
    text_preview: r.text.slice(0, 320),
    text_for_prompt: r.text.slice(0, CHUNK_PROMPT_CAP),
  }));

  return { doc_id: id, strategy: strat, topK: k, results };
}
