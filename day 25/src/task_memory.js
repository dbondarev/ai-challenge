import OpenAI from "openai";

function openaiClient() {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) throw new Error("OPENAI_API_KEY is missing");
  return new OpenAI({ apiKey });
}

function modelName() {
  return (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
}

function parseJson(raw) {
  let text = String(raw || "").trim();
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) text = fence[1].trim();
  const obj = text.match(/\{[\s\S]*\}/);
  if (obj) text = obj[0];
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function uniqAppend(list, items) {
  const out = [...(list || [])];
  const seen = new Set(out.map((x) => String(x).toLowerCase().trim()));
  for (const it of items || []) {
    const s = String(it || "").trim();
    if (!s) continue;
    const key = s.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(s);
  }
  return out;
}

export function summarizeTaskState(task) {
  const t = task || {};
  const parts = [];
  if (t.goal) parts.push(`Цель: ${t.goal}`);
  if (t.constraints?.length) parts.push(`Ограничения: ${t.constraints.join("; ")}`);
  if (t.clarifications?.length) {
    parts.push(`Уточнения: ${t.clarifications.slice(-5).join("; ")}`);
  }
  const terms = t.terms || {};
  const keys = Object.keys(terms);
  if (keys.length) {
    parts.push(
      "Термины: " + keys.map((k) => `${k}=${terms[k]}`).join("; ")
    );
  }
  return parts.join("\n") || "(пусто)";
}

export function buildRagQuery(userMessage, task) {
  const msg = String(userMessage || "").trim();
  const summary = summarizeTaskState(task);
  if (!task?.goal && !task?.constraints?.length) return msg;
  return `${msg}\n\n[Контекст задачи]\n${summary}`;
}

/**
 * Merge LLM delta into existing task_state.
 */
export function mergeTaskState(prev, delta) {
  const base = {
    goal: prev?.goal || "",
    clarifications: [...(prev?.clarifications || [])],
    constraints: [...(prev?.constraints || [])],
    terms: { ...(prev?.terms || {}) },
  };
  if (!delta || typeof delta !== "object") return base;

  const newGoal = String(delta.goal || "").trim();
  if (newGoal) base.goal = newGoal;

  base.clarifications = uniqAppend(base.clarifications, delta.clarifications);
  base.constraints = uniqAppend(base.constraints, delta.constraints);

  if (delta.terms && typeof delta.terms === "object") {
    for (const [k, v] of Object.entries(delta.terms)) {
      const key = String(k || "").trim();
      const val = String(v || "").trim();
      if (key && val) base.terms[key] = val;
    }
  }
  return base;
}

/**
 * Update task memory from recent dialogue + current user message.
 */
export async function updateTaskState({ taskState, recentMessages, userMessage }) {
  const openai = openaiClient();
  const hist = (recentMessages || [])
    .slice(-8)
    .map((m) => `${m.role}: ${m.content}`)
    .join("\n");

  const completion = await openai.chat.completions.create({
    model: modelName(),
    temperature: 0,
    messages: [
      {
        role: "system",
        content:
          "Ты экстрактор памяти задачи для RAG-чата. Верни ТОЛЬКО JSON: " +
          '{"goal":string,"clarifications":string[],"constraints":string[],"terms":{string:string}}. ' +
          "goal — текущая цель диалога (обнови если пользователь сменил цель). " +
          "clarifications — что пользователь уже уточнил. " +
          "constraints — ограничения (например «только про внимание»). " +
          "terms — зафиксированные термины и их смысл. " +
          "Не выдумывай; опирайся на диалог. Если goal ещё неясен — краткая гипотеза из первого вопроса.",
      },
      {
        role: "user",
        content:
          `Текущая память:\n${JSON.stringify(taskState || {}, null, 2)}\n\n` +
          `Недавний диалог:\n${hist || "(пусто)"}\n\n` +
          `Новое сообщение пользователя: ${String(userMessage || "").trim()}`,
      },
    ],
  });

  const delta = parseJson(completion.choices[0]?.message?.content || "");
  return mergeTaskState(taskState, delta);
}
