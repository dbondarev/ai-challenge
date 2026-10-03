import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";
import express from "express";

import {
  DAY21_ROOT,
  DAY24_ROOT,
  DAY25_ROOT,
  day21,
} from "./bridge.js";
import { handleTurn } from "./chat.js";
import { runAllScenarios } from "./scenario_run.js";
import {
  createSession,
  deleteSession,
  loadSession,
} from "./session_store.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

const app = express();
const PORT = Number(process.env.PORT || 5024);

app.use(express.json({ limit: "1mb" }));
app.use(express.static(resolve(ROOT, "templates")));

let scenarioRunning = false;

app.get("/", (_req, res) => {
  res.sendFile(resolve(ROOT, "templates/index.html"));
});

app.get("/api/status", async (_req, res) => {
  try {
    const d21 = await day21();
    const docs = d21.docs_db.listDocs();
    const active = d21.docs_db.getActiveDoc();
    const indexes = d21.index_store.indexStatus(docs.active_id);
    res.json({
      ok: true,
      port: PORT,
      has_openai: Boolean((process.env.OPENAI_API_KEY || "").trim()),
      model: (process.env.OPENAI_MODEL || "gpt-4o-mini").trim(),
      history_turns: Number(process.env.HISTORY_TURNS || 6),
      know_min_score: Number(process.env.KNOW_MIN_SCORE || 0.38),
      day21_root: DAY21_ROOT,
      day24_root: DAY24_ROOT,
      day25_root: DAY25_ROOT,
      active,
      active_id: docs.active_id,
      indexes,
      scenario_running: scenarioRunning,
    });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.post("/api/session", (_req, res) => {
  const session = createSession();
  res.json({
    ok: true,
    session_id: session.id,
    task_state: session.task_state,
    messages: [],
  });
});

app.get("/api/session/:id", (req, res) => {
  const session = loadSession(req.params.id);
  if (!session) {
    return res.status(404).json({ ok: false, error: "session not found" });
  }
  res.json({
    ok: true,
    session_id: session.id,
    task_state: session.task_state,
    messages: session.messages,
  });
});

app.delete("/api/session/:id", (req, res) => {
  deleteSession(req.params.id);
  res.json({ ok: true });
});

app.post("/api/chat", async (req, res) => {
  try {
    const message = String(req.body?.message || "").trim();
    const session_id = String(req.body?.session_id || "").trim() || undefined;
    const docId = String(req.body?.docId || "").trim() || undefined;
    if (!message) {
      return res.status(400).json({ ok: false, error: "message required" });
    }
    const result = await handleTurn({ sessionId: session_id, message, docId });
    res.json({ ok: true, ...result });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.post("/api/scenario/run", async (_req, res) => {
  if (scenarioRunning) {
    return res.status(409).json({ ok: false, error: "scenario already running" });
  }
  scenarioRunning = true;
  try {
    const report = await runAllScenarios();
    res.json({ ok: true, summary: report.summary, results: report.results });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  } finally {
    scenarioRunning = false;
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`[day25] http://127.0.0.1:${PORT}`);
});
