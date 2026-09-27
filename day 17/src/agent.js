import OpenAI from "openai";

import { McpSession } from "./mcp_session.js";

const MAX_TOOL_ROUNDS = 3;

const SYSTEM = `You are the Day 17 agent. You have MCP tools for Microsoft 365 mail (m365-mail).
For mailbox connection / account status questions, call m365_connection_status.
Never invent tool results - always use the tool output.
Answer the user briefly in the same language they used, based on the tool result.`;

/**
 * Convert MCP tool descriptor to OpenAI function tool.
 */
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
  return {
    type: "function",
    function: {
      name: tool.name,
      description: tool.description || tool.name,
      parameters,
    },
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
 * Run one user turn: MCP connect, OpenAI tool loop, disconnect.
 * @param {string} userText
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

  const session = new McpSession();
  const toolTrace = [];

  try {
    await session.connect();
    const mcpTools = await session.listTools();
    const tools = mcpTools.map(mcpToolToOpenAI);

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
        const name = tc.function?.name || "";
        const args = parseArgs(tc.function?.arguments);
        const called = await session.callTool(name, args);
        toolTrace.push({
          id: tc.id,
          name: called.name,
          arguments: called.arguments,
          result: called.result,
          isError: called.isError,
        });
        messages.push({
          role: "tool",
          tool_call_id: tc.id,
          content: called.result || "(empty)",
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

    return {
      ok: true,
      reply: reply || "(no reply)",
      tool_trace: toolTrace,
      mcp_tools: mcpTools.map((t) => t.name),
      server: session.launch,
      model,
    };
  } catch (err) {
    const stderr = session.stderrText();
    const base = err instanceof Error ? err.message : String(err);
    throw new Error(stderr ? `${base}\n--- server stderr ---\n${stderr}` : base);
  } finally {
    await session.close();
  }
}
