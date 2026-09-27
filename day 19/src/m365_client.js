import { existsSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import {
  StdioClientTransport,
  getDefaultEnvironment,
} from "@modelcontextprotocol/sdk/client/stdio.js";

const DAY19_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_SERVER_SCRIPT = resolve(
  DAY19_ROOT,
  "../../MCP/mcp/m365-mail/dist/index.js"
);

const M365_ENV_KEYS = [
  "M365_TENANT_ID",
  "M365_CLIENT_ID",
  "M365_REDIRECT_URI",
  "M365_PREFERRED_ACCOUNT_UPN",
];

export function resolveServerLaunch() {
  const command = (process.env.MCP_SERVER_COMMAND || "node").trim();
  const rawArgs = (process.env.MCP_SERVER_ARGS || "").trim();
  let args;
  if (rawArgs) {
    args = rawArgs.split(/\s+/).filter(Boolean);
  } else {
    args = [DEFAULT_SERVER_SCRIPT];
  }
  if (args[0] && !isAbsolute(args[0]) && args[0].endsWith(".js")) {
    args[0] = resolve(DAY19_ROOT, args[0]);
  }
  return { command, args, serverScript: args[0] };
}

function childEnv() {
  const env = { ...getDefaultEnvironment() };
  for (const key of M365_ENV_KEYS) {
    const val = process.env[key];
    if (val != null && String(val).trim() !== "") {
      env[key] = String(val).trim();
    }
  }
  return env;
}

function contentToText(content) {
  if (!Array.isArray(content)) return String(content ?? "");
  return content
    .map((c) => {
      if (c?.type === "text") return c.text || "";
      return JSON.stringify(c);
    })
    .filter(Boolean)
    .join("\n");
}

/**
 * One-shot call to an m365-mail MCP tool.
 */
export async function callM365Tool(name, args = {}) {
  const launch = resolveServerLaunch();
  if (launch.serverScript?.endsWith(".js") && !existsSync(launch.serverScript)) {
    throw new Error(`MCP server script not found: ${launch.serverScript}`);
  }

  const transport = new StdioClientTransport({
    command: launch.command,
    args: launch.args,
    env: childEnv(),
    stderr: "pipe",
  });
  const stderrChunks = [];
  transport.stderr?.on("data", (c) =>
    stderrChunks.push(Buffer.from(c).toString("utf8"))
  );

  const client = new Client(
    { name: "day19-compose", version: "0.1.0" },
    { capabilities: {} }
  );

  try {
    await client.connect(transport);
    const result = await client.callTool({
      name,
      arguments: args && typeof args === "object" ? args : {},
    });
    const text = contentToText(result.content);
    let parsed = null;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
    if (result.isError || parsed?.error) {
      throw new Error(parsed?.error || text || `${name} failed`);
    }
    return { text, parsed, raw: result };
  } catch (err) {
    const stderr = stderrChunks.join("").trim();
    const base = err instanceof Error ? err.message : String(err);
    throw new Error(stderr ? `${base}\n--- stderr ---\n${stderr}` : base);
  } finally {
    try {
      await client.close();
    } catch {
      /* */
    }
    try {
      await transport.close();
    } catch {
      /* */
    }
  }
}

export { DAY19_ROOT };
