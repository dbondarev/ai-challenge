import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";

import { DAY23_ROOT, day22EvalSet } from "./bridge.js";
import { answerBaseline, answerEnhanced } from "./rag.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

function norm(s) {
  return String(s || "").toLowerCase().replace(/ё/g, "е");
}

function keywordHits(answer, keywords) {
  const a = norm(answer);
  const hits = [];
  for (const k of keywords || []) {
    if (k && a.includes(norm(k))) hits.push(k);
  }
  return hits;
}

function sectionHits(sources, expectedSections) {
  const joined = (sources || [])
    .map((s) => String(s.section || ""))
    .join(" | ");
  const n = norm(joined);
  const hits = [];
  for (const sec of expectedSections || []) {
    if (sec && n.includes(norm(sec).slice(0, 24))) hits.push(sec);
  }
  return hits;
}

function avgCosine(sources) {
  const list = sources || [];
  if (!list.length) return null;
  const sum = list.reduce((a, s) => a + Number(s.score || 0), 0);
  return sum / list.length;
}

function scoreMode(item, result) {
  const kw = keywordHits(result.answer, item.keywords);
  const sec = sectionHits(result.sources, item.expected_sections);
  const outOf = Boolean(item.out_of_corpus);
  let ok;
  if (outOf) {
    ok = /нет в (базе|контексте)|не сказано|не упомина|не знаю|нет информации|не содержится/i.test(
      result.answer
    );
  } else {
    ok =
      (item.keywords?.length
        ? kw.length / item.keywords.length >= 0.34
        : true) || sec.length > 0;
  }
  return {
    answer: result.answer,
    answer_preview: result.answer.slice(0, 280),
    sources: result.sources,
    hit_sections: [...new Set((result.sources || []).map((s) => s.section))],
    keyword_hits: kw,
    section_hits: sec,
    expect_met_heuristic: ok,
    avg_source_cosine: avgCosine(result.sources),
    source_count: (result.sources || []).length,
    rewrite: result.rewrite || null,
    post_filter_count: result.post_filter_count ?? null,
    pre_count: result.pre_count ?? null,
    fallback: Boolean(result.fallback),
  };
}

function scoreItem(item, baseline, enhanced) {
  return {
    id: item.id,
    question: item.question,
    expect: item.expect,
    expected_sections: item.expected_sections,
    out_of_corpus: Boolean(item.out_of_corpus),
    baseline: scoreMode(item, baseline),
    enhanced: scoreMode(item, enhanced),
  };
}

export async function runEval({ limit } = {}) {
  const { getEvalSet, EVAL_SET } = await day22EvalSet();
  const full = typeof getEvalSet === "function" ? getEvalSet() : EVAL_SET;
  const set = full.slice(0, limit || full.length);
  const rows = [];
  for (const item of set) {
    process.stderr.write(`[eval] ${item.id}…\n`);
    const [baseline, enhanced] = await Promise.all([
      answerBaseline(item.question),
      answerEnhanced(item.question),
    ]);
    rows.push(scoreItem(item, baseline, enhanced));
  }

  const summary = {
    total: rows.length,
    baseline_met: rows.filter((r) => r.baseline.expect_met_heuristic).length,
    enhanced_met: rows.filter((r) => r.enhanced.expect_met_heuristic).length,
    avg_cosine_baseline:
      rows.reduce((a, r) => a + (r.baseline.avg_source_cosine || 0), 0) /
      (rows.length || 1),
    avg_cosine_enhanced:
      rows.reduce((a, r) => a + (r.enhanced.avg_source_cosine || 0), 0) /
      (rows.length || 1),
    avg_sources_after_filter:
      rows.reduce((a, r) => a + (r.enhanced.post_filter_count || 0), 0) /
      (rows.length || 1),
    rewrite_used: rows.filter((r) => r.enhanced.rewrite).length,
  };

  const report = {
    built_at: new Date().toISOString(),
    summary,
    rows,
  };

  const outDir = resolve(DAY23_ROOT, "data/reports");
  const runsDir = resolve(outDir, "eval-runs");
  mkdirSync(runsDir, { recursive: true });
  writeFileSync(resolve(outDir, "eval.json"), JSON.stringify(report, null, 2), "utf8");

  const md = [
    "# Day 23 — Baseline vs Enhanced RAG eval",
    "",
    `Built: ${report.built_at}`,
    "",
    `| mode | expect_met (heuristic) | avg source cosine |`,
    `|---|---:|---:|`,
    `| baseline | ${summary.baseline_met}/${summary.total} | ${summary.avg_cosine_baseline.toFixed(3)} |`,
    `| enhanced | ${summary.enhanced_met}/${summary.total} | ${summary.avg_cosine_enhanced.toFixed(3)} |`,
    "",
    `- avg sources after filter: ${summary.avg_sources_after_filter.toFixed(2)}`,
    `- rewrite used: ${summary.rewrite_used}/${summary.total}`,
    "",
  ];
  for (const r of rows) {
    md.push(`## ${r.id}`);
    md.push("");
    md.push(`**Q:** ${r.question}`);
    md.push("");
    md.push(`**Expect:** ${r.expect}`);
    md.push("");
    md.push(
      `**Baseline** (met=${r.baseline.expect_met_heuristic}; avg_cos=${
        r.baseline.avg_source_cosine != null
          ? r.baseline.avg_source_cosine.toFixed(3)
          : "—"
      }):`
    );
    md.push("");
    md.push(r.baseline.answer_preview);
    md.push("");
    md.push(
      `**Enhanced** (met=${r.enhanced.expect_met_heuristic}; rewrite=\`${
        r.enhanced.rewrite || ""
      }\`; post_filter=${r.enhanced.post_filter_count}; avg_cos=${
        r.enhanced.avg_source_cosine != null
          ? r.enhanced.avg_source_cosine.toFixed(3)
          : "—"
      }):`
    );
    md.push("");
    md.push(r.enhanced.answer_preview);
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
