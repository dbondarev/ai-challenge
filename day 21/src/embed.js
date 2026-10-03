import OpenAI from "openai";

const BATCH = Number(process.env.EMBED_BATCH || 64);

/**
 * Attach embeddings to chunks in place. Returns same array.
 */
export async function embedChunks(chunks, opts = {}) {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) throw new Error("OPENAI_API_KEY is missing");
  const model = (
    opts.model ||
    process.env.EMBEDDING_MODEL ||
    "text-embedding-3-small"
  ).trim();
  const openai = new OpenAI({ apiKey });

  for (let i = 0; i < chunks.length; i += BATCH) {
    const batch = chunks.slice(i, i + BATCH);
    const inputs = batch.map((c) => c.text.slice(0, 8000));
    const vectors = await embedWithRetry(openai, model, inputs);
    for (let j = 0; j < batch.length; j++) {
      batch[j].embedding = vectors[j];
    }
    process.stderr.write(
      `[embed] ${Math.min(i + BATCH, chunks.length)}/${chunks.length}\n`
    );
  }
  return chunks;
}

async function embedWithRetry(openai, model, inputs, attempt = 0) {
  try {
    const res = await openai.embeddings.create({ model, input: inputs });
    const sorted = [...res.data].sort((a, b) => a.index - b.index);
    return sorted.map((d) => d.embedding);
  } catch (err) {
    const status = err?.status || err?.response?.status;
    if ((status === 429 || status === 500 || status === 503) && attempt < 5) {
      const wait = 1000 * Math.pow(2, attempt);
      await new Promise((r) => setTimeout(r, wait));
      return embedWithRetry(openai, model, inputs, attempt + 1);
    }
    throw err;
  }
}

export async function embedQuery(text) {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) throw new Error("OPENAI_API_KEY is missing");
  const model = (process.env.EMBEDDING_MODEL || "text-embedding-3-small").trim();
  const openai = new OpenAI({ apiKey });
  const res = await openai.embeddings.create({
    model,
    input: String(text || "").slice(0, 8000),
  });
  return res.data[0].embedding;
}
