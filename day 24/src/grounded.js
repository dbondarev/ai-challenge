import OpenAI from "openai";

import { day23 } from "./bridge.js";
import { makeRefuse, validateGrounded } from "./validate.js";

function openaiClient() {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) throw new Error("OPENAI_API_KEY is missing");
  return new OpenAI({ apiKey });
}

function modelName() {
  return (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
}

function knowMinScore() {
  return Number(process.env.KNOW_MIN_SCORE || 0.38);
}

function parseJson(raw) {
  let text = String(raw || "").trim();
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) text = fence[1].trim();
  const objMatch = text.match(/\{[\s\S]*\}/);
  if (objMatch) text = objMatch[0];
  try {
    return JSON.parse(text);
  } catch {
    return { refuse: true, answer: "", sources: [], quotes: [] };
  }
}

/**
 * Day 23 enhanced retrieve only (no free-text answer).
 */
export async function retrieveEnhanced(question, opts = {}) {
  const d23 = await day23();
  const kPre = Number(opts.kPre || process.env.K_PRE || 12);
  const kPost = Number(opts.kPost || process.env.K_POST || 5);
  const threshold = Number(
    opts.threshold != null ? opts.threshold : process.env.SIM_THRESHOLD || 0.32
  );

  const rw = await d23.rewrite.rewriteQuery(question);
  const retrieval = await d23.retrieve.retrieve({
    question: rw.rewritten,
    docId: opts.docId,
    strategy: opts.strategy,
    topK: kPre,
  });
  const pre = retrieval.results;
  const filtered = d23.filter_rerank.applyThreshold(pre, threshold);
  const reranked = await d23.filter_rerank.llmRerank(question, filtered.kept);
  const post = reranked.chunks.slice(0, kPost);

  return {
    rewrite: rw.rewritten,
    rewrite_meta: rw,
    pre_count: pre.length,
    post_filter_count: filtered.post_filter_count,
    fallback: filtered.fallback,
    threshold: filtered.threshold,
    k_pre: kPre,
    k_post: kPost,
    chunks: post,
    dropped_count: (filtered.dropped || []).length,
    retrieval: {
      doc_id: retrieval.doc_id,
      strategy: retrieval.strategy,
      topK: retrieval.topK,
    },
  };
}

async function llmGroundedAnswer(question, chunks) {
  const contextBlocks = chunks.map((r, i) => {
    const n = i + 1;
    return (
      `[${n}] source=${r.source || "?"} section=${r.section || "?"} ` +
      `chunk_id=${r.chunk_id} cosine=${Number(r.score).toFixed(3)}\n` +
      (r.text_for_prompt || String(r.text || "").slice(0, 1200))
    );
  });
  const context = contextBlocks.join("\n\n---\n\n") || "(контекст пуст)";

  const openai = openaiClient();
  const completion = await openai.chat.completions.create({
    model: modelName(),
    temperature: 0,
    messages: [
      {
        role: "system",
        content:
          "Ты ассистент по базе знаний (RAG). Отвечай СТРОГО JSON без markdown. " +
          "Схема: {\"refuse\":boolean,\"answer\":string,\"sources\":[{\"n\":number,\"source\":string,\"section\":string,\"chunk_id\":string}],\"quotes\":[{\"n\":number,\"text\":string}]}. " +
          "Опирайся ТОЛЬКО на контекст. quotes.text — ДОСЛОВНЫЕ короткие фрагменты из текста чанков (подстроки). " +
          "В answer указывай ссылки [n]. Отвечай по смыслу: если в контексте есть формулировка " +
          "(например время, внимание и энергия как три опоры/категории/компонента) — это ответ, " +
          "даже без дословного слова «компоненты». " +
          "refuse=true только если в контексте действительно нет релевантных фактов; тогда answer с «не знаю» и просьбой уточнить, sources=[], quotes=[]. " +
          "Не выдумывай факты, источники и цитаты.",
      },
      {
        role: "user",
        content: `Контекст:\n${context}\n\nВопрос: ${String(question || "").trim()}`,
      },
    ],
  });
  return parseJson(completion.choices[0]?.message?.content || "");
}

/**
 * Full grounded ask: retrieve → KNOW gate → JSON answer → validate.
 */
export async function answerGrounded(question, opts = {}) {
  const q = String(question || "").trim();
  if (!q) throw new Error("question required");

  const meta = await retrieveEnhanced(q, opts);
  const chunks = meta.chunks || [];
  const scores = chunks.map((c) => Number(c.score || 0));
  const maxCosine = scores.length ? Math.max(...scores) : 0;
  const know = knowMinScore();

  const retrieval_meta = {
    rewrite: meta.rewrite,
    pre_count: meta.pre_count,
    post_filter_count: meta.post_filter_count,
    fallback: meta.fallback,
    threshold: meta.threshold,
    k_pre: meta.k_pre,
    k_post: meta.k_post,
    max_cosine: maxCosine,
    know_min_score: know,
    dropped_count: meta.dropped_count,
    retrieval: meta.retrieval,
    gate_passed: false,
  };

  if (
    chunks.length === 0 ||
    meta.fallback === true ||
    maxCosine < know
  ) {
    const reason =
      chunks.length === 0
        ? "no_chunks"
        : meta.fallback
          ? "threshold_fallback"
          : `max_cosine ${maxCosine.toFixed(3)} < KNOW_MIN_SCORE ${know}`;
    const refused = makeRefuse(reason);
    return {
      question: q,
      ...refused,
      retrieval_meta,
      model: modelName(),
    };
  }

  retrieval_meta.gate_passed = true;
  const parsed = await llmGroundedAnswer(q, chunks);
  const validated = validateGrounded(parsed, chunks);

  return {
    question: q,
    ...validated,
    retrieval_meta,
    model: modelName(),
  };
}
