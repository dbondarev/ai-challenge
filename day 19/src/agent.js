import OpenAI from "openai";

import {
  composeCreateRule,
  composeListDay,
  composeListRules,
  composePipeline,
  composeSave,
  composeSearch,
  composeSummarize,
} from "./compose_tools.js";

const MAX_ROUNDS = 5;

const TOOL_DEFS = [
  {
    type: "function",
    function: {
      name: "compose_pipeline",
      description:
        "Preferred for day digest or search+save: auto fetch → summarize → save. Returns steps + path.",
      parameters: {
        type: "object",
        properties: {
          mode: { type: "string", enum: ["day", "search"] },
          query: { type: "string" },
          hours: { type: "number" },
          top: { type: "number" },
          filename: { type: "string" },
        },
        required: ["mode"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "compose_list_day",
      description: "List recent mail (last N hours).",
      parameters: {
        type: "object",
        properties: {
          hours: { type: "number" },
          top: { type: "number" },
        },
      },
    },
  },
  {
    type: "function",
    function: {
      name: "compose_search",
      description: "Search mailbox.",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string" },
          top: { type: "number" },
        },
        required: ["query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "compose_summarize",
      description: "Summarize messages_json or text.",
      parameters: {
        type: "object",
        properties: {
          messages_json: { type: "string" },
          text: { type: "string" },
          label: { type: "string" },
        },
      },
    },
  },
  {
    type: "function",
    function: {
      name: "compose_save",
      description: "Save content to data/out.",
      parameters: {
        type: "object",
        properties: {
          content: { type: "string" },
          filename: { type: "string" },
        },
        required: ["content"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "compose_list_rules",
      description: "List Inbox message rules.",
      parameters: { type: "object", properties: {} },
    },
  },
  {
    type: "function",
    function: {
      name: "compose_create_rule",
      description: "Create rule only after user confirms.",
      parameters: {
        type: "object",
        properties: {
          rule: { type: "object" },
          mailbox: { type: "string" },
        },
        required: ["rule"],
      },
    },
  },
];

const HANDLERS = {
  compose_pipeline: composePipeline,
  compose_list_day: composeListDay,
  compose_search: composeSearch,
  compose_summarize: composeSummarize,
  compose_save: composeSave,
  compose_list_rules: composeListRules,
  compose_create_rule: composeCreateRule,
};

const SYSTEM = `You are Day 19 compose agent for Microsoft 365 mail.
Tools: compose_* (pipeline wraps m365 fetch + summarize + save).
For requests like "сводка за день", "digest", "search and save" — prefer ONE call to compose_pipeline.
Do not invent file paths; only report paths returned by compose_save / compose_pipeline.
Answer the user in the same language they use. Be concise.`;

export async function runAgentChat(userMessage, history = []) {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) {
    throw new Error("OPENAI_API_KEY is not set");
  }
  const model = (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
  const openai = new OpenAI({ apiKey });

  const messages = [
    { role: "system", content: SYSTEM },
    ...history.filter((m) => m.role === "user" || m.role === "assistant"),
    { role: "user", content: String(userMessage || "").trim() },
  ];

  const toolTrace = [];
  let rounds = 0;

  while (rounds < MAX_ROUNDS) {
    rounds += 1;
    const completion = await openai.chat.completions.create({
      model,
      messages,
      tools: TOOL_DEFS,
      tool_choice: "auto",
    });
    const msg = completion.choices[0]?.message;
    if (!msg) throw new Error("Empty OpenAI response");

    if (!msg.tool_calls?.length) {
      return {
        reply: (msg.content || "").trim() || "(empty)",
        toolTrace,
        rounds,
      };
    }

    messages.push({
      role: "assistant",
      content: msg.content || null,
      tool_calls: msg.tool_calls,
    });

    for (const tc of msg.tool_calls) {
      const name = tc.function?.name;
      let args = {};
      try {
        args = JSON.parse(tc.function?.arguments || "{}");
      } catch {
        args = {};
      }
      const handler = HANDLERS[name];
      let result;
      let ok = true;
      try {
        if (!handler) throw new Error(`Unknown tool: ${name}`);
        result = await handler(args);
      } catch (err) {
        ok = false;
        result = { error: err instanceof Error ? err.message : String(err) };
      }
      toolTrace.push({
        name,
        args,
        ok,
        preview: JSON.stringify(result).slice(0, 400),
      });
      messages.push({
        role: "tool",
        tool_call_id: tc.id,
        content: JSON.stringify(result),
      });
    }
  }

  return {
    reply:
      "Достигнут лимит шагов агента. Смотрите toolTrace / используйте кнопку Pipeline.",
    toolTrace,
    rounds,
  };
}
