import { existsSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import {
  StdioClientTransport,
  getDefaultEnvironment,
} from "@modelcontextprotocol/sdk/client/stdio.js";

const DAY17_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_SERVER_SCRIPT = resolve(
  DAY17_ROOT,
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
    args[0] = resolve(DAY17_ROOT, args[0]);
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
      if (c?.type === "image") return "[image]";
      return JSON.stringify(c);
    })
    .filter(Boolean)
    .join("\n");
}

/**
 * One-shot MCP session: connect -> use -> close.
 */
export class McpSession {
  constructor() {
    this.client = null;
    this.transport = null;
    this.stderrChunks = [];
    this.launch = null;
  }

  async connect() {
    const launch = resolveServerLaunch();
    this.launch = launch;
    if (
      launch.serverScript &&
      launch.serverScript.endsWith(".js") &&
      !existsSync(launch.serverScript)
    ) {
      throw new Error(
        `MCP server script not found: ${launch.serverScript}\nBuild m365-mail first.`
      );
    }

    this.transport = new StdioClientTransport({
      command: launch.command,
      args: launch.args,
      env: childEnv(),
      stderr: "pipe",
    });

    const stderr = this.transport.stderr;
    if (stderr) {
      stderr.on("data", (chunk) => {
        this.stderrChunks.push(Buffer.from(chunk).toString("utf8"));
      });
    }

    this.client = new Client(
      { name: "day17-mcp-agent", version: "0.1.0" },
      { capabilities: {} }
    );
    await this.client.connect(this.transport);
    return this;
  }

  async listTools() {
    const result = await this.client.listTools();
    return (result.tools || []).map((t) => ({
      name: t.name,
      description: t.description || "",
      inputSchema: t.inputSchema || null,
    }));
  }

  /**
   * @param {string} name
   * @param {Record<string, unknown>} [args]
   */
  async callTool(name, args = {}) {
    const result = await this.client.callTool({
      name,
      arguments: args && typeof args === "object" ? args : {},
    });
    const text = contentToText(result.content);
    return {
      name,
      arguments: args,
      result: text,
      isError: Boolean(result.isError),
    };
  }

  async close() {
    try {
      if (this.client) await this.client.close();
    } catch {
      /* ignore */
    }
    try {
      if (this.transport) await this.transport.close();
    } catch {
      /* ignore */
    }
    this.client = null;
    this.transport = null;
  }

  stderrText() {
    return this.stderrChunks.join("").trim();
  }
}
