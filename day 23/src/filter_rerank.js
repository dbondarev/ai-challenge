import OpenAI from "openai";

const RERANK_PREVIEW = 400;

function openaiClient() {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) throw new Error("OPENAI_API_KEY is missing");
  return new OpenAI({ apiKey });
}

function modelName() {
  return (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
}

/**
 * Drop chunks with cosine score < threshold.
 * If none remain — keep top-1 pre-filter with fallback flag.
 */
export function applyThreshold(chunks, threshold) {
  const thr = Number(
    threshold != null ? threshold : process.env.SIM_THRESHOLD || 0.32
  );
  const list = Array.isArray(chunks) ? chunks : [];
  const kept = list.filter((c) => Number(c.score) >= thr);
  const dropped = list.filter((c) => Number(c.score) < thr);
  if (kept.length === 0 && list.length > 0) {
    const top = { ...list[0], fallback: true };
    return {
      threshold: thr,
      kept: [top],
      dropped: list.slice(1).concat(
        list[0].score < thr ? [{ ...list[0], dropped_then_fallback: true }] : []
      ),
      fallback: true,
      post_filter_count: 1,
    };
  }
  return {
    threshold: thr,
    kept,
    dropped,
    fallback: false,
    post_filter_count: kept.length,
  };
}

function parseScoresJson(raw, n) {
  let text = String(raw || "").trim();
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) text = fence[1].trim();
  const objMatch = text.match(/\{[\s\S]*\}/);
  if (objMatch) text = objMatch[0];
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return Array(n).fill(5);
  }
  let scores = parsed?.scores;
  if (!Array.isArray(scores)) {
    if (Array.isArray(parsed)) scores = parsed;
    else return Array(n).fill(5);
  }
  const out = [];
  for (let i = 0; i < n; i++) {
    let v = Number(scores[i]);
    if (!Number.isFinite(v)) v = 5;
    v = Math.max(0, Math.min(10, v));
    out.push(v);
  }
  return out;
}

/**
 * LLM rerank: score each chunk 0–10 vs original question; sort desc, tie-break cosine.
 */
export async function llmRerank(question, chunks) {
  const list = Array.isArray(chunks) ? chunks : [];
  if (list.length === 0) {
    return { chunks: [], scores: [], model: modelName() };
  }
  if (list.length === 1) {
    return {
      chunks: [{ ...list[0], rerank_score: 10 }],
      scores: [10],
      model: modelName(),
    };
  }

  const numbered = list
    .map((c, i) => {
      const preview = String(c.text || c.text_preview || "").slice(0, RERANK_PREVIEW);
      return (
        `${i + 1}. section=${c.section || "?"} cosine=${Number(c.score).toFixed(3)}\n` +
        preview
      );
    })
    .join("\n\n");

  const openai = openaiClient();
  const completion = await openai.chat.completions.create({
    model: modelName(),
    temperature: 0,
    messages: [
      {
        role: "system",
        content:
          "Ты реранкер релевантности чанков книги к вопросу пользователя. " +
          "Оцени каждый чанк от 0 до 10 (целое или дробное) по полезности для ответа на ИСХОДНЫЙ вопрос. " +
          'Верни ТОЛЬКО JSON вида {"scores":[...]} длины ровно как число чанков, в том же порядке. Без пояснений.',
      },
      {
        role: "user",
        content:
          `Исходный вопрос: ${String(question || "").trim()}\n\n` +
          `Чанки (${list.length}):\n\n${numbered}`,
      },
    ],
  });

  const raw = completion.choices[0]?.message?.content || "";
  const scores = parseScoresJson(raw, list.length);
  const ranked = list
    .map((c, i) => ({
      ...c,
      rerank_score: scores[i],
    }))
    .sort((a, b) => {
      const d = (b.rerank_score || 0) - (a.rerank_score || 0);
      if (d !== 0) return d;
      return (b.score || 0) - (a.score || 0);
    });

  return { chunks: ranked, scores, model: modelName(), raw };
}
