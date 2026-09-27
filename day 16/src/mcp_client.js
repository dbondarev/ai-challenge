import { existsSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { getDefaultEnvironment } from "@modelcontextprotocol/sdk/client/stdio.js";

const DAY16_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_SERVER_SCRIPT = resolve(
  DAY16_ROOT,
  "../../MCP/mcp/m365-mail/dist/index.js"
);

const M365_ENV_KEYS = [
  "M365_TENANT_ID",
  "M365_CLIENT_ID",
  "M365_REDIRECT_URI",
  "M365_PREFERRED_ACCOUNT_UPN",
];

/**
 * Resolve command + args for the m365-mail MCP server child process.
 */
export function resolveServerLaunch() {
  const command = (process.env.MCP_SERVER_COMMAND || "node").trim();
  const rawArgs = (process.env.MCP_SERVER_ARGS || "").trim();
  let args;
  if (rawArgs) {
    args = rawArgs.split(/\s+/).filter(Boolean);
  } else {
    args = [DEFAULT_SERVER_SCRIPT];
  }
  // Make first arg absolute if it looks like a path to the server entry
  if (args[0] && !isAbsolute(args[0]) && args[0].endsWith(".js")) {
    args[0] = resolve(DAY16_ROOT, args[0]);
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

/**
 * Connect to m365-mail over stdio, list tools, disconnect.
 * @returns {Promise<{ ok: true, connected: true, server: object, tools: object[] }>}
 */
export async function listMcpTools() {
  const { command, args, serverScript } = resolveServerLaunch();

  if (serverScript && serverScript.endsWith(".js") && !existsSync(serverScript)) {
    throw new Error(
      `MCP server script not found: ${serverScript}\n` +
        "Build m365-mail first (see README)."
    );
  }

  const transport = new StdioClientTransport({
    command,
    args,
    env: childEnv(),
    stderr: "pipe",
  });

  const stderrChunks = [];
  const stderr = transport.stderr;
  if (stderr) {
    stderr.on("data", (chunk) => {
      stderrChunks.push(Buffer.from(chunk).toString("utf8"));
    });
  }

  const client = new Client(
    { name: "day16-mcp-client", version: "0.1.0" },
    { capabilities: {} }
  );

  try {
    await client.connect(transport);
    const result = await client.listTools();
    const tools = (result.tools || []).map((t) => ({
      name: t.name,
      description: t.description || "",
      inputSchema: t.inputSchema || null,
    }));

    return {
      ok: true,
      connected: true,
      server: {
        command,
        args,
        script: serverScript,
      },
      tools,
      count: tools.length,
    };
  } catch (err) {
    const stderrText = stderrChunks.join("").trim();
    const base = err instanceof Error ? err.message : String(err);
    throw new Error(
      stderrText ? `${base}\n--- server stderr ---\n${stderrText}` : base
    );
  } finally {
    try {
      await client.close();
    } catch {
      /* ignore */
    }
    try {
      await transport.close();
    } catch {
      /* ignore */
    }
  }
}
