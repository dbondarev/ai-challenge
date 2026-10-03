import { mkdirSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";

import { getActiveDoc } from "./docs_db.js";
import { loadIndex, resolveDocId } from "./index_store.js";
import { docDir } from "./docs_db.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

export function statsForChunks(chunks) {
  const lengths = (chunks || [])
    .map((c) => (c.text || "").length)
    .sort((a, b) => a - b);
  const n = lengths.length;
  const sum = lengths.reduce((a, b) => a + b, 0);
  const avg = n ? sum / n : 0;
  const median = n ? lengths[Math.floor(n / 2)] : 0;
  const p95 = n ? lengths[Math.min(n - 1, Math.floor(n * 0.95))] : 0;
  const tooShort = lengths.filter((l) => l < 40).length;
  const sections = new Set(
    (chunks || []).map((c) => c.section).filter(Boolean)
  );
  return {
    chunk_count: n,
    avg_len: Math.round(avg),
    median_len: median,
    p95_len: p95,
    too_short: tooShort,
    unique_sections: sections.size,
    total_chars: sum,
    sections_sample: [...sections].slice(0, 12),
  };
}

export function compareIndexes(docId) {
  const id = resolveDocId(docId);
  if (!id) {
    throw new Error("No active document. Select or build a document first.");
  }
  const fixed = loadIndex(id, "fixed");
  const structure = loadIndex(id, "structure");
  if (!fixed || !structure) {
    throw new Error(
      `Both indexes required for doc=${id}. Run Build.`
    );
  }
  const a = statsForChunks(fixed.chunks);
  const b = statsForChunks(structure.chunks);
  const report = {
    built_at: new Date().toISOString(),
    doc_id: id,
    fixed: { meta: fixed.meta, stats: a },
    structure: { meta: structure.meta, stats: b },
  };

  const md = [
    `# Day 21 — Chunking comparison (${id})`,
    "",
    `| Metric | fixed | structure |`,
    `|---|---:|---:|`,
    `| chunk_count | ${a.chunk_count} | ${b.chunk_count} |`,
    `| avg length | ${a.avg_len} | ${b.avg_len} |`,
    `| median length | ${a.median_len} | ${b.median_len} |`,
    `| p95 length | ${a.p95_len} | ${b.p95_len} |`,
    `| too_short (<40) | ${a.too_short} | ${b.too_short} |`,
    `| unique sections | ${a.unique_sections} | ${b.unique_sections} |`,
    `| total chars (embed proxy) | ${a.total_chars} | ${b.total_chars} |`,
    "",
    "## Notes",
    "",
    "- **fixed**: sliding window (size/overlap).",
    "- **structure**: Часть/headings, then sub-chunks.",
    "",
    "### Structure sections (sample)",
    "",
    ...b.sections_sample.map((s) => `- ${s}`),
    "",
  ].join("\n");

  const outDir = docDir(id);
  mkdirSync(outDir, { recursive: true });
  writeFileSync(
    resolve(outDir, "comparison.json"),
    JSON.stringify(report, null, 2),
    "utf8"
  );
  writeFileSync(resolve(outDir, "comparison.md"), md, "utf8");

  // Also mirror to data/reports for convenience
  const reports = resolve(ROOT, "data/reports");
  mkdirSync(reports, { recursive: true });
  writeFileSync(
    resolve(reports, "comparison.json"),
    JSON.stringify(report, null, 2),
    "utf8"
  );
  writeFileSync(resolve(reports, "comparison.md"), md, "utf8");

  return report;
}

const isMain =
  process.argv[1] &&
  fileURLToPath(import.meta.url) === resolve(process.argv[1]);
if (isMain) {
  try {
    const active = getActiveDoc();
    const r = compareIndexes(active?.id);
    console.log(JSON.stringify(r, null, 2));
  } catch (e) {
    console.error(e.message || e);
    process.exit(1);
  }
}
