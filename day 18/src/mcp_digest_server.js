/**
 * Stdio MCP server exposing digest_run_now / digest_get_last
 * for Cursor or other MCP clients. Cron still lives in `npm start`.
 */
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import dotenv from "dotenv";
import { z } from "zod";

import { runDigest, digestStatus } from "./digest.js";
import { getLastDigest, listDigests } from "./store.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

const server = new McpServer({
  name: "day18-mail-digest",
  version: "0.1.0",
});

server.registerTool(
  "digest_run_now",
  {
    title: "Run mail digest now",
    description:
      "Immediately run the daily mail digest job (same as 06:00 America/Chicago cron): fetch recent mail via m365-mail, summarize, save JSON, send Telegram.",
    inputSchema: {
      trigger: z
        .string()
        .optional()
        .default("mcp")
        .describe("Label stored in digest history"),
    },
  },
  async ({ trigger }) => {
    try {
      const result = await runDigest({ trigger: trigger || "mcp" });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      return {
        content: [{ type: "text", text: JSON.stringify({ error: msg }, null, 2) }],
        isError: true,
      };
    }
  }
);

server.registerTool(
  "digest_get_last",
  {
    title: "Get last mail digest",
    description: "Return the last saved digest from digests.json (aggregated summary + meta).",
    inputSchema: {},
  },
  async () => {
    const last = getLastDigest();
    const status = digestStatus();
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({ last, status }, null, 2),
        },
      ],
    };
  }
);

server.registerTool(
  "digest_list",
  {
    title: "List recent digests",
    description: "List recent saved digests (newest first).",
    inputSchema: {
      limit: z.number().int().min(1).max(30).optional().default(10),
    },
  },
  async ({ limit }) => {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({ digests: listDigests(limit ?? 10) }, null, 2),
        },
      ],
    };
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
