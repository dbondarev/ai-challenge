#!/usr/bin/env node
/**
 * Day 19 compose MCP server (stdio).
 * Tools: compose_list_day, compose_search, compose_summarize, compose_save,
 *        compose_pipeline, compose_list_rules, compose_create_rule
 */
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import dotenv from "dotenv";
import { z } from "zod";

import {
  composeCreateRule,
  composeListDay,
  composeListRules,
  composePipeline,
  composeSave,
  composeSearch,
  composeSummarize,
} from "./compose_tools.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

function ok(data) {
  return {
    content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
  };
}

function fail(err) {
  const msg = err instanceof Error ? err.message : String(err);
  return {
    content: [{ type: "text", text: JSON.stringify({ error: msg }) }],
    isError: true,
  };
}

const server = new McpServer({
  name: "day19-compose",
  version: "0.1.0",
});

server.registerTool(
  "compose_list_day",
  {
    description: "List recent mailbox messages (proxy to m365_list_recent_messages).",
    inputSchema: {
      hours: z.number().int().min(1).max(168).optional(),
      top: z.number().int().min(1).max(50).optional(),
    },
  },
  async (args) => {
    try {
      return ok(await composeListDay(args));
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "compose_search",
  {
    description: "Search mailbox (proxy to m365_search_messages).",
    inputSchema: {
      query: z.string().min(1),
      top: z.number().int().min(1).max(50).optional(),
    },
  },
  async (args) => {
    try {
      return ok(await composeSearch(args));
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "compose_summarize",
  {
    description: "Summarize messages JSON or free text (Russian).",
    inputSchema: {
      messages_json: z.string().optional(),
      text: z.string().optional(),
      label: z.string().optional(),
    },
  },
  async (args) => {
    try {
      return ok(await composeSummarize(args));
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "compose_save",
  {
    description: "Save content to data/out/*.md and return path.",
    inputSchema: {
      content: z.string().min(1),
      filename: z.string().optional(),
    },
  },
  async (args) => {
    try {
      return ok(await composeSave(args));
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "compose_pipeline",
  {
    description:
      "Auto chain: fetch (day list or search) → summarize → save. Prefer this for digest/search+save.",
    inputSchema: {
      mode: z.enum(["day", "search"]),
      query: z.string().optional(),
      hours: z.number().int().min(1).max(168).optional(),
      top: z.number().int().min(1).max(50).optional(),
      filename: z.string().optional(),
    },
  },
  async (args) => {
    try {
      return ok(await composePipeline(args));
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "compose_list_rules",
  {
    description: "List Inbox message rules (proxy to m365_list_message_rules).",
    inputSchema: {},
  },
  async () => {
    try {
      return ok(await composeListRules());
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "compose_create_rule",
  {
    description:
      "Create an Inbox message rule (proxy to m365_create_message_rule). Use only when user confirms.",
    inputSchema: {
      rule: z.record(z.any()),
      mailbox: z.string().optional(),
    },
  },
  async (args) => {
    try {
      return ok(await composeCreateRule(args));
    } catch (e) {
      return fail(e);
    }
  }
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
