import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";
import express from "express";

import { runAgentTurn } from "./agent.js";
import { resolveServerLaunch } from "./mcp_session.js";

const DAY17_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(DAY17_ROOT, ".env") });

const app = express();
const PORT = Number(process.env.PORT || 5016);

app.use(express.json({ limit: "1mb" }));
app.use(express.static(resolve(DAY17_ROOT, "templates")));

app.get("/", (_req, res) => {
  res.sendFile(resolve(DAY17_ROOT, "templates/index.html"));
});

app.get("/api/health", (_req, res) => {
  const launch = resolveServerLaunch();
  res.json({
    ok: true,
    port: PORT,
    model: process.env.OPENAI_MODEL || "gpt-4o-mini",
    has_openai_key: Boolean((process.env.OPENAI_API_KEY || "").trim()),
    mcp: launch,
  });
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
  console.log(`Day 17 UI: http://127.0.0.1:${PORT}`);
});
