#!/usr/bin/env node
/**
 * Thin stdio MCP for Singularity REST API v2 (fallback when remote HTTP MCP auth fails).
 * Tools: singularity_list_projects, singularity_list_tasks, singularity_create_task, singularity_get_task
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const BASE = (
  process.env.SINGULARITY_API_BASE || "https://api.singularity-app.com"
).replace(/\/$/, "");
const TOKEN = (process.env.SINGULARITY_TOKEN || "").trim();

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

async function api(method, path, body) {
  if (!TOKEN) throw new Error("SINGULARITY_TOKEN is not set");
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    throw new Error(
      `Singularity API ${method} ${path} → ${res.status}: ${typeof data === "string" ? data : JSON.stringify(data)}`
    );
  }
  return data;
}

const server = new McpServer({
  name: "day20-singularity-stdio",
  version: "0.1.0",
});

server.registerTool(
  "singularity_list_projects",
  {
    description: "List Singularity projects (GET /v2/project).",
    inputSchema: {
      maxCount: z.number().int().min(1).max(200).optional(),
      offset: z.number().int().min(0).optional(),
    },
  },
  async ({ maxCount, offset }) => {
    try {
      const qs = new URLSearchParams();
      if (maxCount != null) qs.set("maxCount", String(maxCount));
      if (offset != null) qs.set("offset", String(offset));
      const q = qs.toString() ? `?${qs}` : "";
      return ok(await api("GET", `/v2/project${q}`));
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "singularity_list_tasks",
  {
    description:
      "List Singularity tasks (GET /v2/task). Optional projectId / inbox filters if supported by API.",
    inputSchema: {
      maxCount: z.number().int().min(1).max(200).optional(),
      offset: z.number().int().min(0).optional(),
      projectId: z.string().optional(),
    },
  },
  async ({ maxCount, offset, projectId }) => {
    try {
      const qs = new URLSearchParams();
      if (maxCount != null) qs.set("maxCount", String(maxCount));
      if (offset != null) qs.set("offset", String(offset));
      if (projectId) qs.set("projectId", projectId);
      const q = qs.toString() ? `?${qs}` : "";
      return ok(await api("GET", `/v2/task${q}`));
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "singularity_get_task",
  {
    description: "Get one Singularity task by id (GET /v2/task/{id}).",
    inputSchema: {
      id: z.string().min(1),
    },
  },
  async ({ id }) => {
    try {
      return ok(await api("GET", `/v2/task/${encodeURIComponent(id)}`));
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "singularity_create_task",
  {
    description:
      "Create a Singularity task (POST /v2/task). Prefer titles starting with [Day20] for demos.",
    inputSchema: {
      title: z.string().min(1),
      note: z.string().optional(),
      projectId: z.string().optional(),
      priority: z.number().int().optional(),
      start: z.string().optional(),
      deadline: z.string().optional(),
    },
  },
  async ({ title, note, projectId, priority, start, deadline }) => {
    try {
      const body = { title };
      if (note != null) body.note = note;
      if (projectId != null) body.projectId = projectId;
      if (priority != null) body.priority = priority;
      if (start != null) body.start = start;
      if (deadline != null) body.deadline = deadline;
      return ok(await api("POST", "/v2/task", body));
    } catch (e) {
      return fail(e);
    }
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
