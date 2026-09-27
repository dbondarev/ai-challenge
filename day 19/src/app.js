import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";
import express from "express";

import { runAgentChat } from "./agent.js";
import {
  composeCreateRule,
  composeListFolders,
  composeListRules,
  composePipeline,
  OUT_DIR,
} from "./compose_tools.js";
import { resolveServerLaunch } from "./m365_client.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

const app = express();
const PORT = Number(process.env.PORT || 5018);

app.use(express.json({ limit: "2mb" }));
app.use(express.static(resolve(ROOT, "templates")));

app.get("/", (_req, res) => {
  res.sendFile(resolve(ROOT, "templates/index.html"));
});

app.get("/api/status", (_req, res) => {
  const launch = resolveServerLaunch();
  res.json({
    ok: true,
    port: PORT,
    has_openai: Boolean((process.env.OPENAI_API_KEY || "").trim()),
    openai_model: (process.env.OPENAI_MODEL || "gpt-4o-mini").trim(),
    mcp: launch,
    out_dir: OUT_DIR,
  });
});

app.post("/api/pipeline", async (req, res) => {
  try {
    const mode = String(req.body?.mode || "day");
    const result = await composePipeline({
      mode: mode === "search" ? "search" : "day",
      query: req.body?.query || "",
      hours: Number(req.body?.hours || 24),
      top: Number(req.body?.top || 30),
      filename: req.body?.filename,
    });
    res.json(result);
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.post("/api/rules/list", async (_req, res) => {
  try {
    const result = await composeListRules();
    res.json({ ok: true, ...result });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.get("/api/folders", async (_req, res) => {
  try {
    const result = await composeListFolders();
    res.json({ ok: true, ...result });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.post("/api/rules/create", async (req, res) => {
  try {
    if (!req.body?.confirm) {
      return res.status(400).json({
        ok: false,
        error: "confirm=true required to create a rule",
      });
    }
    const displayName = String(req.body?.displayName || "").trim();
    const senderContains = String(req.body?.senderContains || "").trim();
    const moveToFolder = String(req.body?.moveToFolder || "").trim();
    if (!displayName || !senderContains || !moveToFolder) {
      return res.status(400).json({
        ok: false,
        error: "displayName, senderContains, moveToFolder required",
      });
    }
    const sequence = Number(req.body?.sequence || 1);
    const rule = {
      displayName,
      sequence,
      isEnabled: true,
      conditions: {
        senderContains: [senderContains],
      },
      actions: {
        moveToFolder,
        stopProcessingRules: true,
      },
    };
    const result = await composeCreateRule({
      rule,
      mailbox: req.body?.mailbox,
    });
    res.json({ ok: true, ...result });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.post("/api/chat", async (req, res) => {
  try {
    const message = String(req.body?.message || "").trim();
    if (!message) {
      return res.status(400).json({ ok: false, error: "message required" });
    }
    const history = Array.isArray(req.body?.history) ? req.body.history : [];
    const result = await runAgentChat(message, history);
    res.json({ ok: true, ...result });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.listen(PORT, () => {
  console.log(`[day19] http://127.0.0.1:${PORT}`);
});
