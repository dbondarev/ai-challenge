import OpenAI from "openai";

import { day24 } from "./bridge.js";
import {
  getOrCreateSession,
  saveSession,
} from "./session_store.js";
import {
  buildRagQuery,
  summarizeTaskState,
  updateTaskState,
} from "./task_memory.js";

function openaiClient() {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) throw new Error("OPENAI_API_KEY is missing");
  return new OpenAI({ apiKey });
}

function modelName() {
  return (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
}

function historyTurns() {
  return Number(process.env.HISTORY_TURNS || 6);
}

/**
 * Compose final reply using grounded RAG answer + history + task state.
 * Does not invent facts beyond grounded answer; keeps sources/quotes from Day 24.
 */
async function composeReply({
  userMessage,
  grounded,
  taskState,
  recentMessages,
}) {
  if (grounded.refuse) {
    return grounded.answer;
  }

  const hist = (recentMessages || [])
    .slice(-historyTurns() * 2)
    .map((m) => `${m.role}: ${m.content}`)
    .join("\n");

  const openai = openaiClient();
  const completion = await openai.chat.completions.create({
    model: modelName(),
    temperature: 0.2,
    messages: [
      {
        role: "system",
        content:
          "Ты ассистент чата с RAG. Переформулируй ответ с учётом цели задачи и истории. " +
          "НЕ добавляй факты, которых нет в «Ответ из базы». Сохраняй ссылки [n]. " +
          "Кратко на русском. Если цель/ограничения в памяти — учитывай их в формулировке.",
      },
      {
        role: "user",
        content:
          `Память задачи:\n${summarizeTaskState(taskState)}\n\n` +
          `История:\n${hist || "(пусто)"}\n\n` +
          `Вопрос пользователя: ${userMessage}\n\n` +
          `Ответ из базы:\n${grounded.answer}\n\n` +
          `Источники (не перечисляй списком — уже будут отдельно): ` +
          `${(grounded.sources || []).map((s) => `[${s.n}] ${s.section}`).join("; ")}`,
      },
    ],
  });
  return (completion.choices[0]?.message?.content || grounded.answer).trim();
}

/**
 * One chat turn: update memory → RAG (Day 24) → compose → persist.
 */
export async function handleTurn({ sessionId, message, docId } = {}) {
  const text = String(message || "").trim();
  if (!text) throw new Error("message required");

  const session = getOrCreateSession(sessionId);
  const recent = session.messages.map((m) => ({
    role: m.role,
    content: m.content,
  }));

  const task_state = await updateTaskState({
    taskState: session.task_state,
    recentMessages: recent,
    userMessage: text,
  });
  session.task_state = task_state;

  const ragQuery = buildRagQuery(text, task_state);
  const d24 = await day24();
  const grounded = await d24.grounded.answerGrounded(ragQuery, { docId });

  const reply = await composeReply({
    userMessage: text,
    grounded,
    taskState: task_state,
    recentMessages: recent,
  });

  session.messages.push({
    role: "user",
    content: text,
    at: new Date().toISOString(),
  });
  session.messages.push({
    role: "assistant",
    content: reply,
    sources: grounded.sources || [],
    quotes: grounded.quotes || [],
    refuse: Boolean(grounded.refuse),
    retrieval_meta: grounded.retrieval_meta || null,
    rag_query: ragQuery,
    at: new Date().toISOString(),
  });
  saveSession(session);

  return {
    session_id: session.id,
    reply,
    answer: reply,
    sources: grounded.sources || [],
    quotes: grounded.quotes || [],
    refuse: Boolean(grounded.refuse),
    task_state,
    retrieval_meta: grounded.retrieval_meta || null,
    validation: grounded.validation || null,
    rag_query: ragQuery,
  };
}
