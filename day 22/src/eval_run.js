import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";

import { DAY22_ROOT } from "./day21_bridge.js";
import { getEvalSet } from "./eval_set.js";
import { answerWithRag, answerWithoutRag } from "./rag.js";

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

function scoreItem(item, rag, noRag) {
  const kwRag = keywordHits(rag.answer, item.keywords);
  const kwNo = keywordHits(noRag.answer, item.keywords);
  const secRag = sectionHits(rag.sources, item.expected_sections);
  const outOf = Boolean(item.out_of_corpus);

  let ragOk;
  let noRagOk;
  if (outOf) {
    const refusal =
      /нет в (базе|контексте)|не сказано|не упомина|не знаю|нет информации|не содержится/i.test(
        rag.answer
      );
    ragOk = refusal;
    noRagOk = !/\d{2,}/.test(noRag.answer); // crude: hallucinated numbers look "confident"
  } else {
    ragOk =
      (item.keywords?.length
        ? kwRag.length / item.keywords.length >= 0.34
        : true) || secRag.length > 0;
    noRagOk = item.keywords?.length
      ? kwNo.length / item.keywords.length >= 0.34
      : false;
  }

  return {
    id: item.id,
    question: item.question,
    expect: item.expect,
    expected_sections: item.expected_sections,
    out_of_corpus: outOf,
    rag: {
      answer: rag.answer,
      answer_preview: rag.answer.slice(0, 280),
      sources: rag.sources,
      hit_sections: [...new Set((rag.sources || []).map((s) => s.section))],
      keyword_hits: kwRag,
      section_hits: secRag,
      expect_met_heuristic: ragOk,
    },
    no_rag: {
      answer: noRag.answer,
      answer_preview: noRag.answer.slice(0, 280),
      keyword_hits: kwNo,
      expect_met_heuristic: noRagOk,
    },
  };
}

export async function runEval({ limit } = {}) {
  const set = getEvalSet().slice(0, limit || getEvalSet().length);
  const rows = [];
  for (const item of set) {
    process.stderr.write(`[eval] ${item.id}…\n`);
    const [rag, noRag] = await Promise.all([
      answerWithRag(item.question),
      answerWithoutRag(item.question),
    ]);
    rows.push(scoreItem(item, rag, noRag));
  }

  const summary = {
    total: rows.length,
    rag_met: rows.filter((r) => r.rag.expect_met_heuristic).length,
    no_rag_met: rows.filter((r) => r.no_rag.expect_met_heuristic).length,
  };

  const report = {
    built_at: new Date().toISOString(),
    summary,
    rows,
  };

  const outDir = resolve(DAY22_ROOT, "data/reports");
  const runsDir = resolve(outDir, "eval-runs");
  mkdirSync(runsDir, { recursive: true });
  writeFileSync(resolve(outDir, "eval.json"), JSON.stringify(report, null, 2), "utf8");

  const md = [
    "# Day 22 — RAG eval",
    "",
    `Built: ${report.built_at}`,
    "",
    `| mode | expect_met (heuristic) |`,
    `|---|---:|`,
    `| rag | ${summary.rag_met}/${summary.total} |`,
    `| no_rag | ${summary.no_rag_met}/${summary.total} |`,
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
      `**RAG** (met=${r.rag.expect_met_heuristic}; sections=${(r.rag.hit_sections || []).join(", ") || "—"}):`
    );
    md.push("");
    md.push(r.rag.answer_preview);
    md.push("");
    md.push(`**No RAG** (met=${r.no_rag.expect_met_heuristic}):`);
    md.push("");
    md.push(r.no_rag.answer_preview);
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
