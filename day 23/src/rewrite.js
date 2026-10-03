import OpenAI from "openai";

function openaiClient() {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) throw new Error("OPENAI_API_KEY is missing");
  return new OpenAI({ apiKey });
}

function modelName() {
  return (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
}

/**
 * Rewrite user question into a short Russian search query (entities / keywords).
 * Does not answer the question.
 */
export async function rewriteQuery(question) {
  const q = String(question || "").trim();
  if (!q) throw new Error("question required");

  const openai = openaiClient();
  const completion = await openai.chat.completions.create({
    model: modelName(),
    temperature: 0.2,
    messages: [
      {
        role: "system",
        content:
          "Ты помощник для поиска по книге. Перепиши вопрос пользователя в короткий " +
          "поисковый запрос на русском: 1–2 предложения или ключевые сущности/термины. " +
          "НЕ отвечай на вопрос. НЕ добавляй пояснений. Только текст запроса.",
      },
      { role: "user", content: q },
    ],
  });
  const rewritten = (completion.choices[0]?.message?.content || "").trim();
  return {
    original: q,
    rewritten: rewritten || q,
    model: modelName(),
  };
}
