import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";

import { runAgentTurn } from "../src/agent.js";
import { MultiMcpHub } from "../src/mcp_hub.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

async function main() {
  console.log("=== Day 20 smoke: hub connect + listTools ===");
  const hub = new MultiMcpHub();
  try {
    await hub.connect();
    const tools = await hub.listTools();
    const by = {};
    for (const t of tools) by[t.server] = (by[t.server] || 0) + 1;
    console.log("status", JSON.stringify(hub.statusSnapshot(), null, 2));
    console.log("tool_counts", by);
    if ((by.m365 || 0) < 1) throw new Error("expected m365 tools");
    if ((by.singularity || 0) < 1) throw new Error("expected singularity tools");
    console.log(
      "sample tools:",
      tools.slice(0, 8).map((t) => t.name).join(", ")
    );
  } finally {
    await hub.close();
  }

  console.log("=== agent cross-server turn ===");
  const prompt =
    "Найди в почте письма по запросу invoice (m365 search, top небольшой). " +
    "Затем создай в Singularity одну задачу с title '[Day20] smoke: разобрать invoice mail' " +
    "и note с кратким списком subject из найденных писем. Не создавай больше одной задачи.";

  const result = await runAgentTurn(prompt);
  console.log("reply:", (result.reply || "").slice(0, 600));
  console.log(
    "trace:",
    JSON.stringify(
      (result.tool_trace || []).map((t) => ({
        order: t.order,
        server: t.server,
        tool: t.tool,
        ok: t.ok,
      })),
      null,
      2
    )
  );
  console.log("servers_used", result.servers_used);
  console.log("cross_server", result.cross_server);

  const servers = new Set((result.tool_trace || []).map((t) => t.server));
  if (!servers.has("m365")) throw new Error("smoke: no m365 tool call");
  if (!servers.has("singularity")) throw new Error("smoke: no singularity tool call");

  const firstMail = (result.tool_trace || []).find((t) => t.server === "m365");
  const firstSing = (result.tool_trace || []).find(
    (t) => t.server === "singularity"
  );
  if (firstMail && firstSing && firstMail.order > firstSing.order) {
    console.warn(
      "warn: singularity called before m365 (order may still be ok for list-first flows)"
    );
  }

  console.log("SMOKE OK");
}

main().catch((err) => {
  console.error("SMOKE FAIL:", err instanceof Error ? err.message : err);
  process.exit(1);
});
