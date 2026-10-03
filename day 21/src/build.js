import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";

import { chunkFixed } from "./chunk_fixed.js";
import { chunkStructure } from "./chunk_structure.js";
import { compareIndexes } from "./compare.js";
import {
  makeDocId,
  setActiveDoc,
  upsertDoc,
} from "./docs_db.js";
import { embedChunks } from "./embed.js";
import { saveIndex } from "./index_store.js";
import { loadText, resolveBookPath } from "./load_text.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

/**
 * Build indexes for a document path. Registers doc in catalog and sets active.
 */
export async function buildAll(opts = {}) {
  const smoke = Boolean(opts.smoke);
  const bookPath = resolve(opts.path || resolveBookPath());
  console.log("[build] loading", bookPath);
  const doc = loadText(bookPath);
  const docId = opts.docId || makeDocId(bookPath);
  console.log(
    `[build] doc_id=${docId} chars=${doc.chars} title=${doc.title.slice(0, 60)}`
  );

  const workDoc = smoke
    ? {
        ...doc,
        text: doc.text.slice(0, 60000),
        chars: Math.min(doc.chars, 60000),
      }
    : doc;

  console.log("[build] chunk fixed…");
  let fixed = chunkFixed(workDoc);
  console.log("[build] chunk structure…");
  let structure = chunkStructure(workDoc);

  if (smoke) {
    fixed = fixed.slice(0, 40);
    structure = structure.slice(0, 40);
    console.log(
      `[build] smoke cap → fixed=${fixed.length} structure=${structure.length}`
    );
  }

  console.log(`[build] embedding fixed (${fixed.length})…`);
  await embedChunks(fixed);
  const savedFixed = saveIndex(docId, "fixed", fixed, {
    source: doc.source,
    source_abs: doc.source_abs,
    title: doc.title,
    smoke,
    full_chars: doc.chars,
    indexed_chars: workDoc.chars,
  });

  console.log(`[build] embedding structure (${structure.length})…`);
  await embedChunks(structure);
  const savedStruct = saveIndex(docId, "structure", structure, {
    source: doc.source,
    source_abs: doc.source_abs,
    title: doc.title,
    smoke,
    full_chars: doc.chars,
    indexed_chars: workDoc.chars,
  });

  upsertDoc({
    id: docId,
    path: doc.source_abs,
    source: doc.source,
    title: doc.title,
    author: doc.author || "",
    chars: doc.chars,
    built_at: new Date().toISOString(),
    smoke,
    strategies: { fixed: true, structure: true },
    chunk_counts: {
      fixed: fixed.length,
      structure: structure.length,
    },
  });
  setActiveDoc(docId);

  const comparison = compareIndexes(docId);
  return {
    ok: true,
    doc_id: docId,
    fixed: savedFixed,
    structure: savedStruct,
    comparison,
  };
}

const isMain =
  process.argv[1] &&
  fileURLToPath(import.meta.url) === resolve(process.argv[1]);

if (isMain) {
  const smoke = process.argv.includes("--smoke");
  const pathArg = process.argv.find((a) => a.startsWith("--path="));
  const path = pathArg ? pathArg.slice("--path=".length) : undefined;
  buildAll({ smoke, path })
    .then((r) => {
      console.log(
        JSON.stringify(
          {
            ok: r.ok,
            doc_id: r.doc_id,
            fixed: r.fixed.meta,
            structure: r.structure.meta,
            compare_chunks: {
              fixed: r.comparison.fixed.stats.chunk_count,
              structure: r.comparison.structure.stats.chunk_count,
            },
          },
          null,
          2
        )
      );
    })
    .catch((e) => {
      console.error(e);
      process.exit(1);
    });
}
