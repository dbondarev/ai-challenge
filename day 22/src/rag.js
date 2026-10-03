import OpenAI from "openai";

import { day21 } from "./day21_bridge.js";

const CHUNK_PROMPT_CAP = 1200;

function openaiClient() {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) throw new Error("OPENAI_API_KEY is missing");
  return new OpenAI({ apiKey });
}

function modelName() {
  return (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
}

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
  const k = Number(topK || process.env.RAG_TOP_K || 5);
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

export async function answerWithoutRag(question) {
  const openai = openaiClient();
  const completion = await openai.chat.completions.create({
    model: modelName(),
    messages: [
      {
        role: "system",
        content:
          "Отвечай кратко на русском по общим знаниям. Если не уверен — так и скажи. Не выдумывай цитаты из конкретных книг.",
      },
      { role: "user", content: String(question || "").trim() },
    ],
  });
  return {
    mode: "no_rag",
    answer: (completion.choices[0]?.message?.content || "").trim(),
    sources: [],
    model: modelName(),
  };
}

export async function answerWithRag(question, opts = {}) {
  const retrieval = await retrieve({
    question,
    docId: opts.docId,
    strategy: opts.strategy,
    topK: opts.topK,
  });

  const contextBlocks = retrieval.results.map((r, i) => {
    const n = i + 1;
    return `[${n}] section=${r.section || "?"} chunk_id=${r.chunk_id} score=${r.score.toFixed(3)}\n${r.text_for_prompt}`;
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

  return {
    mode: "rag",
    answer: (completion.choices[0]?.message?.content || "").trim(),
    sources: retrieval.results.map((r) => ({
      chunk_id: r.chunk_id,
      section: r.section,
      score: r.score,
      text_preview: r.text_preview,
      source: r.source,
    })),
    retrieval: {
      doc_id: retrieval.doc_id,
      strategy: retrieval.strategy,
      topK: retrieval.topK,
    },
    model: modelName(),
  };
}

/**
 * @param {{ question: string, mode?: "rag"|"no_rag"|"both", docId?: string, topK?: number }} opts
 */
export async function answerQuestion(opts = {}) {
  const question = String(opts.question || "").trim();
  if (!question) throw new Error("question required");
  const mode = opts.mode || "both";

  if (mode === "no_rag") {
    return { question, ...await answerWithoutRag(question) };
  }
  if (mode === "rag") {
    return { question, ...await answerWithRag(question, opts) };
  }
  // both — parallel
  const [rag, no_rag] = await Promise.all([
    answerWithRag(question, opts),
    answerWithoutRag(question),
  ]);
  return { question, mode: "both", rag, no_rag };
}
