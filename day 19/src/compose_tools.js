import { mkdirSync, writeFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import OpenAI from "openai";

import { callM365Tool, DAY19_ROOT } from "./m365_client.js";

const OUT_DIR = resolve(DAY19_ROOT, "data/out");

function normalizeMessages(parsed) {
  const items = Array.isArray(parsed?.value)
    ? parsed.value
    : Array.isArray(parsed)
      ? parsed
      : [];
  return items.map((m) => ({
    id: m.id,
    subject: m.subject || "(no subject)",
    from:
      m.from?.emailAddress?.address ||
      m.from?.emailAddress?.name ||
      (typeof m.from === "string" ? m.from : "?"),
    receivedDateTime: m.receivedDateTime,
    bodyPreview: (m.bodyPreview || "").slice(0, 280),
  }));
}

export async function composeListDay({ hours = 24, top = 30 } = {}) {
  const { text, parsed } = await callM365Tool("m365_list_recent_messages", {
    hours,
    top,
  });
  const messages = normalizeMessages(parsed);
  return {
    tool: "compose_list_day",
    hours,
    top,
    count: messages.length,
    messages,
    messages_json: JSON.stringify(messages),
    raw_text: text,
  };
}

export async function composeSearch({ query, top = 20 } = {}) {
  const q = String(query || "").trim();
  if (!q) throw new Error("query is required");
  const { text, parsed } = await callM365Tool("m365_search_messages", {
    query: q,
    top,
  });
  const messages = normalizeMessages(parsed);
  return {
    tool: "compose_search",
    query: q,
    top,
    count: messages.length,
    messages,
    messages_json: JSON.stringify(messages),
    raw_text: text,
  };
}

export async function composeSummarize({ messages_json, text, label = "mail" } = {}) {
  let payload = text;
  let count = 0;
  if (messages_json) {
    let msgs;
    try {
      msgs = JSON.parse(messages_json);
    } catch {
      throw new Error("messages_json must be valid JSON");
    }
    if (!Array.isArray(msgs)) throw new Error("messages_json must be an array");
    count = msgs.length;
    payload = JSON.stringify(msgs.slice(0, 40), null, 2);
  }
  if (!payload || !String(payload).trim()) {
    throw new Error("messages_json or text required");
  }

  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  let summary;
  if (!apiKey) {
    summary = fallbackSummary(payload, count, label);
  } else {
    const model = (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
    const openai = new OpenAI({ apiKey });
    const completion = await openai.chat.completions.create({
      model,
      messages: [
        {
          role: "system",
          content:
            "Summarize mail data in concise Russian. Include count, themes, senders, action items. Max ~1200 chars. No markdown tables.",
        },
        {
          role: "user",
          content: `Label: ${label}\nData:\n${String(payload).slice(0, 12000)}`,
        },
      ],
    });
    summary =
      (completion.choices[0]?.message?.content || "").trim() ||
      fallbackSummary(payload, count, label);
  }

  return {
    tool: "compose_summarize",
    label,
    count,
    summary,
  };
}

function fallbackSummary(payload, count, label) {
  const n = count || "?";
  return `Сводка (${label}): ${n} элементов.\n${String(payload).slice(0, 800)}`;
}

export async function composeSave({ content, filename } = {}) {
  const body = String(content || "").trim();
  if (!body) throw new Error("content is required");
  mkdirSync(OUT_DIR, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  let name = (filename || `pipeline-${ts}.md`).trim();
  name = basename(name).replace(/[^\w.\-а-яА-ЯёЁ]+/gi, "_");
  if (!name.endsWith(".md") && !name.endsWith(".txt")) name += ".md";
  const path = resolve(OUT_DIR, name);
  const fileBody =
    `# Day 19 pipeline result\n\nSaved: ${new Date().toISOString()}\n\n---\n\n` +
    body +
    "\n";
  writeFileSync(path, fileBody, "utf8");
  return {
    tool: "compose_save",
    path,
    filename: name,
    bytes: Buffer.byteLength(fileBody, "utf8"),
  };
}

export async function composeListRules() {
  const { text, parsed } = await callM365Tool("m365_list_message_rules", {});
  return { tool: "compose_list_rules", raw_text: text, parsed };
}

export async function composeListFolders() {
  const { text, parsed } = await callM365Tool("m365_list_mail_folders", {
    top: 50,
  });
  return { tool: "compose_list_folders", raw_text: text, parsed };
}

export async function composeCreateRule({ rule, mailbox } = {}) {
  if (!rule || typeof rule !== "object") {
    throw new Error("rule object is required");
  }
  const args = { rule };
  if (mailbox) args.mailbox = mailbox;
  const { text, parsed } = await callM365Tool("m365_create_message_rule", args);
  return { tool: "compose_create_rule", raw_text: text, parsed };
}

/**
 * Automatic chain: fetch -> summarize -> save.
 */
export async function composePipeline({
  mode = "day",
  query = "",
  hours = 24,
  top = 30,
  filename,
} = {}) {
  const steps = [];

  let fetchResult;
  if (mode === "search") {
    fetchResult = await composeSearch({ query, top });
    steps.push({
      step: 1,
      name: "compose_search",
      ok: true,
      preview: {
        query: fetchResult.query,
        count: fetchResult.count,
      },
      result_preview: fetchResult.messages_json.slice(0, 500),
    });
  } else {
    fetchResult = await composeListDay({ hours, top });
    steps.push({
      step: 1,
      name: "compose_list_day",
      ok: true,
      preview: { hours: fetchResult.hours, count: fetchResult.count },
      result_preview: fetchResult.messages_json.slice(0, 500),
    });
  }

  const sum = await composeSummarize({
    messages_json: fetchResult.messages_json,
    label: mode === "search" ? `search:${query}` : `day:${hours}h`,
  });
  steps.push({
    step: 2,
    name: "compose_summarize",
    ok: true,
    preview: { count: sum.count },
    result_preview: sum.summary.slice(0, 500),
  });

  const saved = await composeSave({
    content: sum.summary,
    filename:
      filename ||
      (mode === "search"
        ? `search-${Date.now()}.md`
        : `day-summary-${Date.now()}.md`),
  });
  steps.push({
    step: 3,
    name: "compose_save",
    ok: true,
    preview: { filename: saved.filename },
    result_preview: saved.path,
  });

  return {
    ok: true,
    mode,
    steps,
    summary: sum.summary,
    path: saved.path,
    mail_count: fetchResult.count,
  };
}

export { OUT_DIR };
