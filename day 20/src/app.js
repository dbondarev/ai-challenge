import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";
import express from "express";

import { runAgentTurn } from "./agent.js";
import { MultiMcpHub } from "./mcp_hub.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

const app = express();
const PORT = Number(process.env.PORT || 5019);

app.use(express.json({ limit: "2mb" }));
app.use(express.static(resolve(ROOT, "templates")));

app.get("/", (_req, res) => {
  res.sendFile(resolve(ROOT, "templates/index.html"));
});

app.get("/api/status", async (_req, res) => {
  const hub = new MultiMcpHub();
  try {
    await hub.connect();
    const tools = await hub.listTools();
    const byServer = {};
    for (const t of tools) {
      byServer[t.server] = (byServer[t.server] || 0) + 1;
    }
    res.json({
      ok: true,
      port: PORT,
      has_openai: Boolean((process.env.OPENAI_API_KEY || "").trim()),
      openai_model: (process.env.OPENAI_MODEL || "gpt-4o-mini").trim(),
      hub: hub.statusSnapshot(),
      tool_counts: byServer,
      tool_total: tools.length,
    });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
      has_openai: Boolean((process.env.OPENAI_API_KEY || "").trim()),
      has_singularity_token: Boolean(
        (process.env.SINGULARITY_TOKEN || "").trim()
      ),
      hub: hub.statusSnapshot(),
    });
  } finally {
    await hub.close();
  }
});

app.get("/api/tools", async (_req, res) => {
  const hub = new MultiMcpHub();
  try {
    await hub.connect();
    const tools = await hub.listTools();
    res.json({
      ok: true,
      tools: tools.map((t) => ({
        name: t.name,
        server: t.server,
        description: t.description,
      })),
    });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  } finally {
    await hub.close();
  }
});

app.post("/api/chat", async (req, res) => {
  try {
    const text = String(req.body?.text || req.body?.message || "");
    const result = await runAgentTurn(text);
    res.json(result);
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`[day20] http://127.0.0.1:${PORT}`);
});
