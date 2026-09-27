import OpenAI from "openai";

import { MultiMcpHub } from "./mcp_hub.js";

const MAX_TOOL_ROUNDS = 16;
/** Max chars of a single tool result fed back into the LLM context. */
const MAX_TOOL_RESULT_CHARS = Number(process.env.DAY20_MAX_TOOL_RESULT_CHARS || 6000);
/** Soft cap on total tool-result chars kept in the conversation. */
const MAX_TOTAL_TOOL_CHARS = Number(process.env.DAY20_MAX_TOTAL_TOOL_CHARS || 40000);

/**
 * Only expose tools needed for mail → inbox tasks.
 * Full Singularity catalog (50+) blows the functions budget and invites over-fetch.
 */
const TOOL_ALLOWLIST = new Set([
  "m365__m365_connection_status",
  "m365__m365_search_messages",
  "m365__m365_list_recent_messages",
  "m365__m365_read_message",
  "singularity__createTask",
  "singularity__listTasks",
  "singularity__getTask",
  "singularity__updateTask",
  "singularity__listProjects",
]);

const SYSTEM = `You are the Day 20 orchestration agent with TWO MCP servers.
Tools are prefixed: m365__* (mail) and singularity__* (SingularityApp).

## Context limits (critical)
- NEVER pull a whole week of mail in one call. Process in SMALL BATCHES.
- Prefer m365__m365_list_recent_messages with hours≤24 and top≤15, then move the window (e.g. next day via search received: or another hours window). API max hours is 72 — for "last week" do several day-sized batches, not one dump.
- For m365__m365_search_messages use top≤10.
- Do NOT call m365__m365_read_message for every message. Only read 1–2 when subject/preview is unclear whether action is needed.
- Tool results you see are already truncated/compacted — work from subjects + previews.

## What becomes a Singularity task
- ONLY actionable items the user must do (reply, pay, decide, send, review, schedule).
- SKIP: shipping/order confirmations that need no action, newsletters, marketing, automatic receipts, password resets, pure FYI notifications.
- Create tasks with singularity__createTask into inbox (omit projectId unless user named a project).
- Titles start with "[Day20]". One createTask per actionable item (or a short checklist note if many similar).
- After each mail batch: create the tasks for that batch, THEN fetch the next batch. Do not accumulate all mail then create everything at once.

## Routing
- Mail → m365__ only. Tasks → singularity__ only.
- Never invent email contents or task ids.
- Answer in the user's language. End with: batches processed, tasks created count, ordered tool list.`;

export function mcpToolToOpenAI(tool) {
  let parameters = tool.inputSchema;
  if (
    !parameters ||
    typeof parameters !== "object" ||
    Array.isArray(parameters) ||
    Object.keys(parameters).length === 0
  ) {
    parameters = { type: "object", properties: {} };
  } else if (!parameters.type) {
    parameters = { type: "object", ...parameters };
  }
  const safeName = String(tool.name).replace(/[^a-zA-Z0-9_-]/g, "_");
  return {
    type: "function",
    function: {
      name: safeName,
      description: tool.description || tool.name,
      parameters,
    },
    _hubName: tool.name,
  };
}

function parseArgs(raw) {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

/**
 * Compact Graph mail payloads so the model sees actionable fields only.
 */
export function compactToolResultForLlm(text, maxChars = MAX_TOOL_RESULT_CHARS) {
  let raw = String(text ?? "");
  if (!raw) return "(empty)";

  try {
    const data = JSON.parse(raw);
    const items = Array.isArray(data?.value)
      ? data.value
      : Array.isArray(data?.messages)
        ? data.messages
        : Array.isArray(data)
          ? data
          : null;

    if (items) {
      const compact = items.slice(0, 20).map((m) => ({
        id: m.id,
        subject: m.subject || "(no subject)",
        from:
          m.from?.emailAddress?.address ||
          m.from?.emailAddress?.name ||
          (typeof m.from === "string" ? m.from : undefined),
        receivedDateTime: m.receivedDateTime,
        preview: String(m.bodyPreview || m.preview || "").slice(0, 180),
        isRead: m.isRead,
        hasAttachments: m.hasAttachments,
      }));
      raw = JSON.stringify(
        {
          count: items.length,
          shown: compact.length,
          truncated_list: items.length > compact.length,
          messages: compact,
        },
        null,
        0
      );
    } else if (data && typeof data === "object") {
      // Single message / task create response — drop huge HTML bodies
      const slim = { ...data };
      if (slim.body?.content) {
        slim.body = {
          contentType: slim.body.contentType,
          content: String(slim.body.content).slice(0, 400),
        };
      }
      if (typeof slim.bodyPreview === "string") {
        slim.bodyPreview = slim.bodyPreview.slice(0, 300);
      }
      raw = JSON.stringify(slim, null, 0);
    }
  } catch {
    /* keep raw text */
  }

  if (raw.length <= maxChars) return raw;
  return (
    raw.slice(0, maxChars) +
    `\n…[truncated ${raw.length - maxChars} chars for context limit]`
  );
}

function clampMailFetchArgs(hubName, args) {
  const out = { ...(args || {}) };
  const tool = hubName.includes("__") ? hubName.split("__").slice(1).join("__") : hubName;

  if (tool === "m365_list_recent_messages") {
    if (out.top == null || Number(out.top) > 15) out.top = 15;
    if (out.hours == null || Number(out.hours) > 48) out.hours = 24;
  }
  if (tool === "m365_search_messages") {
    if (out.top == null || Number(out.top) > 10) out.top = 10;
  }
  return out;
}

/**
 * One user turn across both MCP servers.
 */
export async function runAgentTurn(userText) {
  const text = (userText || "").trim();
  if (!text) throw new Error("Empty message");

  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey || apiKey === "sk-your-key-here") {
    throw new Error("OPENAI_API_KEY is missing");
  }
  const model = (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
  const openai = new OpenAI({ apiKey });

  const hub = new MultiMcpHub();
  const toolTrace = [];
  let mcpTools = [];
  let toolCharsUsed = 0;

  try {
    await hub.connect();
    const allTools = await hub.listTools();
    mcpTools = allTools.filter((t) => TOOL_ALLOWLIST.has(t.name));
    if (!mcpTools.length) {
      // Fallback if names differ (e.g. stdio proxy)
      mcpTools = allTools.filter(
        (t) =>
          t.name.includes("search") ||
          t.name.includes("list_recent") ||
          t.name.includes("createTask") ||
          t.name.includes("create_task") ||
          t.name.includes("listTasks")
      );
    }

    const mapped = mcpTools.map(mcpToolToOpenAI);
    const nameMap = new Map(mapped.map((t) => [t.function.name, t._hubName]));
    const tools = mapped.map(({ type, function: fn }) => ({ type, function: fn }));

    const messages = [
      { role: "system", content: SYSTEM },
      { role: "user", content: text },
    ];

    let reply = "";
    for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
      const completion = await openai.chat.completions.create({
        model,
        messages,
        tools: tools.length ? tools : undefined,
        tool_choice: tools.length ? "auto" : undefined,
      });

      const msg = completion.choices[0]?.message;
      if (!msg) throw new Error("Empty completion from OpenAI");

      const toolCalls = msg.tool_calls || [];
      if (!toolCalls.length) {
        reply = (msg.content || "").trim();
        break;
      }

      messages.push({
        role: "assistant",
        content: msg.content || null,
        tool_calls: toolCalls,
      });

      for (const tc of toolCalls) {
        const openaiName = tc.function?.name || "";
        const hubName = nameMap.get(openaiName) || openaiName;
        let args = parseArgs(tc.function?.arguments);
        args = clampMailFetchArgs(hubName, args);

        if (toolCharsUsed >= MAX_TOTAL_TOOL_CHARS) {
          const stopMsg = JSON.stringify({
            error:
              "Context budget exhausted for this turn. Summarize what you have and create remaining tasks from compacted previews only, or ask user to continue with the next day batch.",
            toolCharsUsed,
            max: MAX_TOTAL_TOOL_CHARS,
          });
          toolTrace.push({
            order: toolTrace.length + 1,
            server: "local",
            tool: "context_budget",
            name: "context_budget",
            arguments: {},
            args_preview: "{}",
            result_preview: stopMsg.slice(0, 400),
            result: stopMsg,
            ok: false,
            isError: true,
          });
          messages.push({
            role: "tool",
            tool_call_id: tc.id,
            content: stopMsg,
          });
          continue;
        }

        const called = await hub.callTool(hubName, args);
        const compact = compactToolResultForLlm(called.result, MAX_TOOL_RESULT_CHARS);
        toolCharsUsed += compact.length;

        toolTrace.push({
          order: called.order,
          server: called.server,
          tool: called.tool,
          name: called.name,
          arguments: called.arguments,
          args_preview: called.args_preview,
          result_preview: compact.slice(0, 500),
          result: compact,
          ok: called.ok,
          isError: called.isError,
          compacted: compact.length < String(called.result || "").length,
        });
        messages.push({
          role: "tool",
          tool_call_id: tc.id,
          content: compact,
        });
      }
    }

    if (!reply) {
      const final = await openai.chat.completions.create({
        model,
        messages,
      });
      reply = (final.choices[0]?.message?.content || "").trim();
    }

    const serversUsed = [...new Set(toolTrace.map((t) => t.server))];
    return {
      ok: true,
      reply: reply || "(no reply)",
      tool_trace: toolTrace,
      servers_used: serversUsed,
      cross_server:
        serversUsed.includes("m365") && serversUsed.includes("singularity"),
      mcp_tools: mcpTools.map((t) => ({
        name: t.name,
        server: t.server,
      })),
      hub: hub.statusSnapshot(),
      model,
      rounds_max: MAX_TOOL_ROUNDS,
      tool_chars_used: toolCharsUsed,
    };
  } finally {
    await hub.close();
  }
}
