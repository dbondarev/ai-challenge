const REFUSE_TEXT =
  "Не знаю по этой базе — уверенность слишком низкая. Уточните вопрос или укажите тему/раздел из книги.";

function norm(s) {
  return String(s || "")
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Check quote is a substring of chunk text (normalized whitespace).
 */
export function quoteInChunk(quote, chunkText) {
  const q = norm(quote);
  if (q.length < 8) return false;
  const hay = norm(chunkText);
  return hay.includes(q);
}

function chunkByIndex(chunks, n) {
  const i = Number(n) - 1;
  if (i >= 0 && i < chunks.length) return chunks[i];
  return null;
}

function sourceFromChunk(chunk, n) {
  return {
    n,
    source: chunk.source || "",
    section: chunk.section || "",
    chunk_id: chunk.chunk_id || "",
    score: chunk.score,
    rerank_score: chunk.rerank_score,
  };
}

/**
 * Validate LLM JSON against retrieved chunks.
 * Forces refuse if no grounded quotes/sources when claiming an answer.
 */
export function validateGrounded(parsed, chunks) {
  const list = Array.isArray(chunks) ? chunks : [];
  const notes = [];
  let refuse = Boolean(parsed?.refuse);

  let rawQuotes = Array.isArray(parsed?.quotes) ? parsed.quotes : [];
  const groundedQuotes = [];
  for (const q of rawQuotes) {
    const text = String(q?.text || "").trim();
    if (!text) continue;
    let n = Number(q?.n);
    if (!Number.isFinite(n) || n < 1) n = 1;
    let chunk = chunkByIndex(list, n);
    let ok = chunk && quoteInChunk(text, chunk.text || chunk.text_for_prompt || "");
    if (!ok) {
      // try any chunk
      const hit = list.findIndex((c) =>
        quoteInChunk(text, c.text || c.text_for_prompt || "")
      );
      if (hit >= 0) {
        n = hit + 1;
        chunk = list[hit];
        ok = true;
        notes.push(`quote remapped to chunk [${n}]`);
      }
    }
    if (ok) {
      groundedQuotes.push({ n, text: text.slice(0, 500) });
    } else {
      notes.push(`dropped ungrounded quote: ${text.slice(0, 60)}…`);
    }
  }

  // Normalize sources from real chunk metadata for cited n's
  const citedNs = new Set(groundedQuotes.map((q) => q.n));
  let rawSources = Array.isArray(parsed?.sources) ? parsed.sources : [];
  for (const s of rawSources) {
    const n = Number(s?.n);
    if (Number.isFinite(n) && n >= 1 && n <= list.length) citedNs.add(n);
  }
  // If answer cites [n], include those
  const answerText = String(parsed?.answer || "");
  for (const m of answerText.matchAll(/\[(\d+)\]/g)) {
    const n = Number(m[1]);
    if (n >= 1 && n <= list.length) citedNs.add(n);
  }

  let sources = [...citedNs]
    .sort((a, b) => a - b)
    .filter((n) => n >= 1 && n <= list.length)
    .map((n) => sourceFromChunk(list[n - 1], n));

  if (!refuse && sources.length === 0 && list.length > 0 && groundedQuotes.length > 0) {
    sources = groundedQuotes.map((q) => sourceFromChunk(list[q.n - 1], q.n));
  }

  if (!refuse) {
    if (groundedQuotes.length === 0 || sources.length === 0) {
      refuse = true;
      notes.push("force refuse: missing grounded quotes or sources");
    }
  }

  const answer = refuse
    ? REFUSE_TEXT
    : String(parsed?.answer || "").trim() || REFUSE_TEXT;

  if (refuse) {
    return {
      refuse: true,
      answer: REFUSE_TEXT,
      sources: [],
      quotes: [],
      validation: {
        ok: true,
        forced_refuse: notes.some((n) => n.startsWith("force")),
        notes,
        quotes_grounded: true,
      },
    };
  }

  return {
    refuse: false,
    answer,
    sources,
    quotes: groundedQuotes,
    validation: {
      ok: groundedQuotes.length > 0 && sources.length > 0,
      forced_refuse: false,
      notes,
      quotes_grounded: true,
    },
  };
}

export function makeRefuse(reason) {
  return {
    refuse: true,
    answer: REFUSE_TEXT,
    sources: [],
    quotes: [],
    validation: {
      ok: true,
      forced_refuse: false,
      gate: true,
      reason: reason || "low_relevance",
      notes: [reason || "low_relevance"],
      quotes_grounded: true,
    },
  };
}

export { REFUSE_TEXT, norm };
