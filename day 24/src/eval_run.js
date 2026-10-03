import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";

import { DAY24_ROOT, day22EvalSet } from "./bridge.js";
import { answerGrounded } from "./grounded.js";
import { norm } from "./validate.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

function tokens(s) {
  return new Set(
    norm(s)
      .split(/[^a-zа-я0-9]+/i)
      .filter((t) => t.length >= 3)
  );
}

function answerAligned(answer, quotes, refuse) {
  if (refuse) return true;
  const qtexts = (quotes || []).map((q) => q.text).join(" ");
  if (!qtexts) return false;
  const citeOk = /\[\d+\]/.test(answer || "");
  const a = tokens(answer);
  const q = tokens(qtexts);
  if (!a.size || !q.size) return citeOk;
  let hit = 0;
  for (const t of a) {
    if (q.has(t)) hit++;
  }
  const overlap = hit / Math.min(a.size, 24);
  return citeOk || overlap >= 0.15;
}

function scoreRow(item, result) {
  const refuse = Boolean(result.refuse);
  const sources = result.sources || [];
  const quotes = result.quotes || [];
  const has_sources = refuse || sources.length >= 1;
  const has_quotes = refuse || quotes.length >= 1;
  const quotes_grounded = Boolean(result.validation?.quotes_grounded) && (
    refuse || quotes.length >= 1
  );
  const answer_aligned = answerAligned(result.answer, quotes, refuse);
  const outOf = Boolean(item.out_of_corpus);
  const refuse_ok = outOf ? refuse === true : true;

  return {
    id: item.id,
    question: item.question,
    expect: item.expect,
    out_of_corpus: outOf,
    refuse,
    answer_preview: String(result.answer || "").slice(0, 280),
    sources_count: sources.length,
    quotes_count: quotes.length,
    max_cosine: result.retrieval_meta?.max_cosine ?? null,
    gate_passed: Boolean(result.retrieval_meta?.gate_passed),
    rewrite: result.retrieval_meta?.rewrite || null,
    checks: {
      has_sources,
      has_quotes,
      quotes_grounded,
      answer_aligned,
      refuse_ok,
    },
    all_ok:
      has_sources &&
      has_quotes &&
      quotes_grounded &&
      answer_aligned &&
      refuse_ok,
  };
}

export async function runEval({ limit } = {}) {
  const { getEvalSet, EVAL_SET } = await day22EvalSet();
  const full = typeof getEvalSet === "function" ? getEvalSet() : EVAL_SET;
  const set = full.slice(0, limit || full.length);
  const rows = [];
  for (const item of set) {
    process.stderr.write(`[eval] ${item.id}…\n`);
    const result = await answerGrounded(item.question);
    rows.push(scoreRow(item, result));
  }

  const summary = {
    total: rows.length,
    all_ok: rows.filter((r) => r.all_ok).length,
    has_sources: rows.filter((r) => r.checks.has_sources).length,
    has_quotes: rows.filter((r) => r.checks.has_quotes).length,
    quotes_grounded: rows.filter((r) => r.checks.quotes_grounded).length,
    answer_aligned: rows.filter((r) => r.checks.answer_aligned).length,
    refuse_ok: rows.filter((r) => r.checks.refuse_ok).length,
    refused: rows.filter((r) => r.refuse).length,
  };

  const report = {
    built_at: new Date().toISOString(),
    summary,
    rows,
  };

  const outDir = resolve(DAY24_ROOT, "data/reports");
  const runsDir = resolve(outDir, "eval-runs");
  mkdirSync(runsDir, { recursive: true });
  writeFileSync(resolve(outDir, "eval.json"), JSON.stringify(report, null, 2), "utf8");

  const md = [
    "# Day 24 — Grounded RAG eval",
    "",
    `Built: ${report.built_at}`,
    "",
    `| check | pass |`,
    `|---|---:|`,
    `| all_ok | ${summary.all_ok}/${summary.total} |`,
    `| has_sources | ${summary.has_sources}/${summary.total} |`,
    `| has_quotes | ${summary.has_quotes}/${summary.total} |`,
    `| quotes_grounded | ${summary.quotes_grounded}/${summary.total} |`,
    `| answer_aligned | ${summary.answer_aligned}/${summary.total} |`,
    `| refuse_ok | ${summary.refuse_ok}/${summary.total} |`,
    `| refused | ${summary.refused}/${summary.total} |`,
    "",
  ];
  for (const r of rows) {
    md.push(`## ${r.id}`);
    md.push("");
    md.push(`**Q:** ${r.question}`);
    md.push("");
    md.push(
      `**Checks:** sources=${r.checks.has_sources} quotes=${r.checks.has_quotes} ` +
        `grounded=${r.checks.quotes_grounded} aligned=${r.checks.answer_aligned} ` +
        `refuse_ok=${r.checks.refuse_ok} | refuse=${r.refuse} max_cos=${
          r.max_cosine != null ? Number(r.max_cosine).toFixed(3) : "—"
        }`
    );
    md.push("");
    md.push(r.answer_preview);
    md.push("");
  }
  writeFileSync(resolve(outDir, "eval.md"), md.join("\n"), "utf8");
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  writeFileSync(
    resolve(runsDir, `eval-${stamp}.json`),
    JSON.stringify(report, null, 2),
    "utf8"
  );
  return report;
}

const isMain =
  process.argv[1] &&
  fileURLToPath(import.meta.url) === resolve(process.argv[1]);

if (isMain) {
  const limitArg = process.argv.find((a) => a.startsWith("--limit="));
  const limit = limitArg ? Number(limitArg.split("=")[1]) : undefined;
  runEval({ limit })
    .then((r) => {
      console.log(JSON.stringify(r.summary, null, 2));
      console.log("Wrote data/reports/eval.md");
    })
    .catch((e) => {
      console.error(e);
      process.exit(1);
    });
}
