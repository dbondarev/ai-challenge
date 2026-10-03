import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";
import express from "express";

import {
  DAY21_ROOT,
  DAY22_ROOT,
  DAY23_ROOT,
  day21,
  day22EvalSet,
} from "./bridge.js";
import { runEval } from "./eval_run.js";
import { answerCompare } from "./rag.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

const app = express();
const PORT = Number(process.env.PORT || 5022);

app.use(express.json({ limit: "1mb" }));
app.use(express.static(resolve(ROOT, "templates")));

let evalRunning = false;

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
      k_pre: Number(process.env.K_PRE || 12),
      k_post: Number(process.env.K_POST || 5),
      rag_top_k: Number(process.env.RAG_TOP_K || 5),
      sim_threshold: Number(process.env.SIM_THRESHOLD || 0.32),
      rag_strategy: (process.env.RAG_STRATEGY || "structure").trim(),
      day21_root: DAY21_ROOT,
      day22_root: DAY22_ROOT,
      day23_root: DAY23_ROOT,
      active,
      active_id: docs.active_id,
      docs_count: (docs.docs || []).length,
      indexes,
      eval_running: evalRunning,
    });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.post("/api/ask", async (req, res) => {
  try {
    const question = String(req.body?.question || "").trim();
    const mode = String(req.body?.mode || "both");
    const docId = String(req.body?.docId || "").trim() || undefined;
    if (!question) {
      return res.status(400).json({ ok: false, error: "question required" });
    }
    if (!["baseline", "enhanced", "both"].includes(mode)) {
      return res
        .status(400)
        .json({ ok: false, error: "mode must be baseline|enhanced|both" });
    }
    const result = await answerCompare({ question, mode, docId });
    res.json({ ok: true, ...result });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.get("/api/eval/set", async (_req, res) => {
  try {
    const mod = await day22EvalSet();
    const questions =
      typeof mod.getEvalSet === "function" ? mod.getEvalSet() : mod.EVAL_SET;
    res.json({ ok: true, questions });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.post("/api/eval/run", async (req, res) => {
  if (evalRunning) {
    return res.status(409).json({ ok: false, error: "eval already running" });
  }
  evalRunning = true;
  try {
    const limit = req.body?.limit != null ? Number(req.body.limit) : undefined;
    const report = await runEval({ limit });
    res.json({ ok: true, summary: report.summary, rows: report.rows });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  } finally {
    evalRunning = false;
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`[day23] http://127.0.0.1:${PORT}`);
});
