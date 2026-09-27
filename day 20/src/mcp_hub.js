import { existsSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import {
  StdioClientTransport,
  getDefaultEnvironment,
} from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const DAY20_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_M365_SCRIPT = resolve(
  DAY20_ROOT,
  "../../MCP/mcp/m365-mail/dist/index.js"
);
const STDIO_SINGULARITY = resolve(
  DAY20_ROOT,
  "src/singularity_stdio_server.js"
);

const M365_ENV_KEYS = [
  "M365_TENANT_ID",
  "M365_CLIENT_ID",
  "M365_REDIRECT_URI",
  "M365_PREFERRED_ACCOUNT_UPN",
];

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

function preview(value, max = 400) {
  const s =
    typeof value === "string" ? value : JSON.stringify(value ?? "", null, 0);
  return s.length > max ? s.slice(0, max) + "…" : s;
}

function resolveM365Launch() {
  const command = (process.env.MCP_SERVER_COMMAND || "node").trim();
  const rawArgs = (process.env.MCP_SERVER_ARGS || "").trim();
  let args;
  if (rawArgs) {
    args = rawArgs.split(/\s+/).filter(Boolean);
  } else {
    args = [DEFAULT_M365_SCRIPT];
  }
  if (args[0] && !isAbsolute(args[0]) && args[0].endsWith(".js")) {
    args[0] = resolve(DAY20_ROOT, args[0]);
  }
  return { command, args, serverScript: args[0] };
}

function m365ChildEnv() {
  const env = { ...getDefaultEnvironment() };
  for (const key of M365_ENV_KEYS) {
    const val = process.env[key];
    if (val != null && String(val).trim() !== "") {
      env[key] = String(val).trim();
    }
  }
  return env;
}

function resolveSingularityToken() {
  return (
    process.env.SINGULARITY_ACCESS_TOKEN ||
    process.env.SINGULARITY_TOKEN ||
    ""
  ).trim();
}

function resolveNativeSingularityLaunch() {
  const command = (
    process.env.SINGULARITY_NATIVE_COMMAND || "bash"
  ).trim();
  const rawArgs = (process.env.SINGULARITY_NATIVE_ARGS || "").trim();
  const defaultScript =
    "/Users/dbondarev/ModumUpCloud/Local/singularity-mcp-server-2.1.1/run-mcp.sh";
  const args = rawArgs
    ? rawArgs.split(/\s+/).filter(Boolean)
    : [defaultScript];
  return { command, args };
}


/**
 * Dual-MCP hub: m365 (stdio) + singularity (HTTP Bearer or stdio REST proxy).
 */
export class MultiMcpHub {
  constructor() {
    /** @type {Map<string, { client: Client, transport: unknown, meta: object }>} */
    this.servers = new Map();
    this.callOrder = 0;
  }

  statusSnapshot() {
    const servers = {};
    for (const [id, entry] of this.servers) {
      servers[id] = {
        connected: true,
        transport: entry.meta.transport,
        detail: entry.meta.detail || null,
      };
    }
    return {
      connected: [...this.servers.keys()],
      servers,
      has_singularity_token: Boolean(resolveSingularityToken()),
      m365: resolveM365Launch(),
      singularity_url: (
        process.env.SINGULARITY_MCP_URL ||
        "https://mcp.singularity-app.com/mcp?toolsets=tasks,projects"
      ).trim(),
      singularity_transport_pref: (
        process.env.SINGULARITY_TRANSPORT || "auto"
      ).trim(),
    };
  }

  async connect() {
    await Promise.all([this.#connectM365(), this.#connectSingularity()]);
    return this;
  }

  async #connectM365() {
    const launch = resolveM365Launch();
    if (
      launch.serverScript?.endsWith(".js") &&
      !existsSync(launch.serverScript)
    ) {
      throw new Error(`m365 MCP script not found: ${launch.serverScript}`);
    }
    const transport = new StdioClientTransport({
      command: launch.command,
      args: launch.args,
      env: m365ChildEnv(),
      stderr: "pipe",
    });
    const client = new Client(
      { name: "day20-m365", version: "0.1.0" },
      { capabilities: {} }
    );
    await client.connect(transport);
    this.servers.set("m365", {
      client,
      transport,
      meta: {
        transport: "stdio",
        detail: launch.args.join(" "),
      },
    });
  }


  async #connectSingularity() {
    const pref = (process.env.SINGULARITY_TRANSPORT || "auto")
      .trim()
      .toLowerCase();
    const token = resolveSingularityToken();
    if (!token) {
      throw new Error(
        "SINGULARITY_ACCESS_TOKEN (or SINGULARITY_TOKEN) is missing. Set it in day 20/.env"
      );
    }

    const errors = [];
    const tryOrder =
      pref === "native"
        ? ["native"]
        : pref === "http"
          ? ["http"]
          : pref === "stdio"
            ? ["stdio"]
            : ["native", "http", "stdio"];

    for (const mode of tryOrder) {
      try {
        if (mode === "native") {
          await this.#connectSingularityNative(token);
          return;
        }
        if (mode === "http") {
          await this.#connectSingularityHttp(token);
          return;
        }
        if (mode === "stdio") {
          await this.#connectSingularityStdio(token);
          return;
        }
      } catch (err) {
        errors.push(
          `${mode}: ${err instanceof Error ? err.message : String(err)}`
        );
      }
    }

    throw new Error(
      `Failed to connect Singularity MCP.\n${errors.join("\n")}`
    );
  }

  async #connectSingularityNative(token) {
    const launch = resolveNativeSingularityLaunch();
    const script = launch.args[0];
    if (script && !existsSync(script)) {
      throw new Error(`Native Singularity MCP script not found: ${script}`);
    }
    const transport = new StdioClientTransport({
      command: launch.command,
      args: launch.args,
      env: {
        ...getDefaultEnvironment(),
        SINGULARITY_ACCESS_TOKEN: token,
        SINGULARITY_BASE_URL: (
          process.env.SINGULARITY_BASE_URL ||
          process.env.SINGULARITY_API_BASE ||
          "https://api.singularity-app.com"
        ).trim(),
      },
      stderr: "pipe",
    });
    const client = new Client(
      { name: "day20-singularity-native", version: "0.1.0" },
      { capabilities: {} }
    );
    await client.connect(transport);
    const tools = await client.listTools();
    if (!tools.tools?.length) {
      throw new Error("Native Singularity MCP returned 0 tools");
    }
    this.servers.set("singularity", {
      client,
      transport,
      meta: {
        transport: "native",
        detail: launch.args.join(" "),
        tool_count: tools.tools.length,
      },
    });
  }

  async #connectSingularityHttp(token) {
    const url = (
      process.env.SINGULARITY_MCP_URL ||
      "https://mcp.singularity-app.com/mcp?toolsets=tasks,projects"
    ).trim();
    const transport = new StreamableHTTPClientTransport(new URL(url), {
      requestInit: {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      },
    });
    const client = new Client(
      { name: "day20-singularity", version: "0.1.0" },
      { capabilities: {} }
    );
    await client.connect(transport);
    // Probe listTools early so we fail fast on auth issues
    const tools = await client.listTools();
    if (!tools.tools?.length) {
      throw new Error("Singularity HTTP MCP connected but returned 0 tools");
    }
    this.servers.set("singularity", {
      client,
      transport,
      meta: {
        transport: "http",
        detail: url,
        tool_count: tools.tools.length,
      },
    });
  }

  async #connectSingularityStdio(token) {
    if (!existsSync(STDIO_SINGULARITY)) {
      throw new Error(`stdio singularity server missing: ${STDIO_SINGULARITY}`);
    }
    const transport = new StdioClientTransport({
      command: "node",
      args: [STDIO_SINGULARITY],
      env: {
        ...getDefaultEnvironment(),
        SINGULARITY_TOKEN: token,
        SINGULARITY_ACCESS_TOKEN: token,
        SINGULARITY_API_BASE: (
          process.env.SINGULARITY_API_BASE ||
          process.env.SINGULARITY_BASE_URL ||
          "https://api.singularity-app.com"
        ).trim(),
      },
      stderr: "pipe",
    });
    const client = new Client(
      { name: "day20-singularity-stdio", version: "0.1.0" },
      { capabilities: {} }
    );
    await client.connect(transport);
    const tools = await client.listTools();
    if (!tools.tools?.length) {
      throw new Error("Singularity stdio MCP returned 0 tools");
    }
    this.servers.set("singularity", {
      client,
      transport,
      meta: {
        transport: "stdio",
        detail: STDIO_SINGULARITY,
        tool_count: tools.tools.length,
      },
    });
  }

  /**
   * @returns {Promise<Array<{ name: string, description: string, inputSchema: object|null, server: string, originalName: string }>>}
   */
  async listTools() {
    const merged = [];
    for (const [serverId, entry] of this.servers) {
      const result = await entry.client.listTools();
      for (const t of result.tools || []) {
        const originalName = t.name;
        const name = `${serverId}__${originalName}`;
        merged.push({
          name,
          originalName,
          server: serverId,
          description: `[${serverId}] ${t.description || originalName}`,
          inputSchema: t.inputSchema || null,
        });
      }
    }
    return merged;
  }

  /**
   * @param {string} prefixedName
   * @param {Record<string, unknown>} [args]
   */
  async callTool(prefixedName, args = {}) {
    const sep = prefixedName.indexOf("__");
    if (sep <= 0) {
      throw new Error(
        `Tool name must be prefixed as server__tool, got: ${prefixedName}`
      );
    }
    const serverId = prefixedName.slice(0, sep);
    const originalName = prefixedName.slice(sep + 2);
    const entry = this.servers.get(serverId);
    if (!entry) {
      throw new Error(`Unknown MCP server: ${serverId}`);
    }

    this.callOrder += 1;
    const order = this.callOrder;
    try {
      const result = await entry.client.callTool({
        name: originalName,
        arguments: args && typeof args === "object" ? args : {},
      });
      const text = contentToText(result.content);
      const isError = Boolean(result.isError);
      return {
        order,
        server: serverId,
        tool: originalName,
        name: prefixedName,
        arguments: args,
        result: text,
        isError,
        args_preview: preview(args, 240),
        result_preview: preview(text, 500),
        ok: !isError,
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        order,
        server: serverId,
        tool: originalName,
        name: prefixedName,
        arguments: args,
        result: msg,
        isError: true,
        args_preview: preview(args, 240),
        result_preview: preview(msg, 500),
        ok: false,
      };
    }
  }

  async close() {
    for (const [, entry] of this.servers) {
      try {
        await entry.client.close();
      } catch {
        /* */
      }
      try {
        if (entry.transport?.close) await entry.transport.close();
      } catch {
        /* */
      }
    }
    this.servers.clear();
  }
}

export { DAY20_ROOT, resolveM365Launch };
