import OpenAI from "openai";

import { applyThreshold, llmRerank } from "./filter_rerank.js";
import { retrieve } from "./retrieve.js";
import { rewriteQuery } from "./rewrite.js";

function openaiClient() {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) throw new Error("OPENAI_API_KEY is missing");
  return new OpenAI({ apiKey });
}

function modelName() {
  return (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
}

function sourceView(r) {
  return {
    chunk_id: r.chunk_id,
    section: r.section,
    score: r.score,
    rerank_score: r.rerank_score,
    fallback: Boolean(r.fallback),
    text_preview: r.text_preview || String(r.text || "").slice(0, 320),
    source: r.source,
  };
}

async function answerFromChunks(question, chunks) {
  const contextBlocks = chunks.map((r, i) => {
    const n = i + 1;
    const rr =
      r.rerank_score != null ? ` rerank=${Number(r.rerank_score).toFixed(1)}` : "";
    return (
      `[${n}] section=${r.section || "?"} chunk_id=${r.chunk_id} ` +
      `cosine=${Number(r.score).toFixed(3)}${rr}\n` +
      (r.text_for_prompt || String(r.text || "").slice(0, 1200))
    );
  });
  const context = contextBlocks.join("\n\n---\n\n") || "(контекст пуст)";

  const openai = openaiClient();
  const completion = await openai.chat.completions.create({
    model: modelName(),
    messages: [
      {
        role: "system",
        content:
          "Ты ассистент по базе знаний (RAG). Отвечай на русском кратко. " +
          "Опирайся ТОЛЬКО на переданный контекст. Указывай номера источников вида [1], [2]. " +
          "Отвечай по смыслу: если в контексте есть формулировка (например время, внимание и энергия " +
          "как три опоры/категории/компонента продуктивности) — это и есть ответ, даже если слово " +
          "«компоненты» не повторяется дословно. " +
          "Говори «в базе этого нет» только если в контексте действительно нет релевантных фактов.",
      },
      {
        role: "user",
        content: `Контекст:\n${context}\n\nВопрос: ${String(question || "").trim()}`,
      },
    ],
  });

  return (completion.choices[0]?.message?.content || "").trim();
}

/** Baseline: raw question → retrieve RAG_TOP_K → answer (no rewrite/threshold/rerank). */
export async function answerBaseline(question, opts = {}) {
  const topK = Number(opts.topK || process.env.RAG_TOP_K || process.env.K_POST || 5);
  const retrieval = await retrieve({
    question,
    docId: opts.docId,
    strategy: opts.strategy,
    topK,
  });
  const answer = await answerFromChunks(question, retrieval.results);
  return {
    mode: "baseline",
    answer,
    sources: retrieval.results.map(sourceView),
    retrieval: {
      doc_id: retrieval.doc_id,
      strategy: retrieval.strategy,
      topK: retrieval.topK,
    },
    model: modelName(),
  };
}

/** Enhanced: rewrite → K_pre → threshold → LLM rerank → K_post → answer. */
export async function answerEnhanced(question, opts = {}) {
  const kPre = Number(opts.kPre || process.env.K_PRE || 12);
  const kPost = Number(opts.kPost || process.env.K_POST || 5);
  const threshold = Number(
    opts.threshold != null ? opts.threshold : process.env.SIM_THRESHOLD || 0.32
  );

  const rw = await rewriteQuery(question);
  const retrieval = await retrieve({
    question: rw.rewritten,
    docId: opts.docId,
    strategy: opts.strategy,
    topK: kPre,
  });
  const pre = retrieval.results;
  const filtered = applyThreshold(pre, threshold);
  const reranked = await llmRerank(question, filtered.kept);
  const post = reranked.chunks.slice(0, kPost);
  const answer = await answerFromChunks(question, post);

  return {
    mode: "enhanced",
    answer,
    rewrite: rw.rewritten,
    rewrite_meta: rw,
    pre_count: pre.length,
    post_filter_count: filtered.post_filter_count,
    fallback: filtered.fallback,
    threshold: filtered.threshold,
    k_pre: kPre,
    k_post: kPost,
    sources_pre: pre.map(sourceView),
    sources_after_filter: filtered.kept.map(sourceView),
    sources: post.map(sourceView),
    dropped: filtered.dropped.map(sourceView),
    rerank_scores: reranked.scores,
    retrieval: {
      doc_id: retrieval.doc_id,
      strategy: retrieval.strategy,
      topK: retrieval.topK,
    },
    model: modelName(),
  };
}

/**
 * @param {{ question: string, mode?: "baseline"|"enhanced"|"both", docId?: string }} opts
 */
export async function answerCompare(opts = {}) {
  const question = String(opts.question || "").trim();
  if (!question) throw new Error("question required");
  const mode = opts.mode || "both";

  if (mode === "baseline") {
    return { question, ...await answerBaseline(question, opts) };
  }
  if (mode === "enhanced") {
    return { question, ...await answerEnhanced(question, opts) };
  }
  const [baseline, enhanced] = await Promise.all([
    answerBaseline(question, opts),
    answerEnhanced(question, opts),
  ]);
  return { question, mode: "both", baseline, enhanced };
}
