import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { docDir, getActiveDoc, loadCatalog } from "./docs_db.js";

export function indexPath(docId, strategy) {
  return resolve(docDir(docId), `${strategy}.json`);
}

export function saveIndex(docId, strategy, chunks, extraMeta = {}) {
  const dir = docDir(docId);
  mkdirSync(dir, { recursive: true });
  const dims = chunks[0]?.embedding?.length || 0;
  const payload = {
    meta: {
      built_at: new Date().toISOString(),
      doc_id: docId,
      strategy,
      chunk_count: chunks.length,
      dims,
      model: (process.env.EMBEDDING_MODEL || "text-embedding-3-small").trim(),
      ...extraMeta,
    },
    chunks,
  };
  const path = indexPath(docId, strategy);
  writeFileSync(path, JSON.stringify(payload), "utf8");
  return { path, meta: payload.meta };
}

export function loadIndex(docId, strategy) {
  if (!docId) return null;
  const path = indexPath(docId, strategy);
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf8"));
}

export function resolveDocId(docId) {
  if (docId) return docId;
  const active = getActiveDoc();
  return active?.id || null;
}

export function indexStatus(docId) {
  const id = resolveDocId(docId);
  const strategies = ["fixed", "structure"];
  const out = { doc_id: id, strategies: {} };
  if (!id) return out;
  for (const s of strategies) {
    const idx = loadIndex(id, s);
    out.strategies[s] = idx
      ? {
          exists: true,
          path: indexPath(id, s),
          meta: idx.meta,
          sample: (idx.chunks || []).slice(0, 3).map(sampleChunk),
        }
      : { exists: false, path: indexPath(id, s) };
  }
  return out;
}

function sampleChunk(c) {
  return {
    chunk_id: c.chunk_id,
    section: c.section,
    char_start: c.char_start,
    char_end: c.char_end,
    text_preview: String(c.text || "").slice(0, 180),
    has_embedding: Array.isArray(c.embedding) && c.embedding.length > 0,
  };
}

export { loadCatalog };
