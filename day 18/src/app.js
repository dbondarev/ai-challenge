import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";
import express from "express";

import { runDigest, digestStatus, isDigestRunning } from "./digest.js";
import { listDigests, getLastDigest } from "./store.js";
import { resolveServerLaunch } from "./mail.js";
import { startScheduler, schedulerInfo } from "./scheduler.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

const app = express();
const PORT = Number(process.env.PORT || 5017);

app.use(express.json({ limit: "1mb" }));
app.use(express.static(resolve(ROOT, "templates")));

const sched = startScheduler();
console.log("[day18] scheduler:", JSON.stringify(sched));

app.get("/", (_req, res) => {
  res.sendFile(resolve(ROOT, "templates/index.html"));
});

app.get("/api/status", (_req, res) => {
  res.json({
    ok: true,
    port: PORT,
    has_openai: Boolean((process.env.OPENAI_API_KEY || "").trim()),
    has_telegram: Boolean(
      (process.env.TELEGRAM_BOT_TOKEN || "").trim() &&
        (process.env.TELEGRAM_CHAT_ID || "").trim()
    ),
    mcp: resolveServerLaunch(),
    scheduler: schedulerInfo(),
    digest: digestStatus(),
    running: isDigestRunning(),
  });
});

app.get("/api/digest/last", (_req, res) => {
  res.json({ ok: true, last: getLastDigest() });
});

app.get("/api/digest/list", (req, res) => {
  const limit = Number(req.query.limit || 10);
  res.json({ ok: true, digests: listDigests(limit) });
});

/** HTTP stand-in for MCP tool digest_run_now */
app.post("/api/digest/run", async (req, res) => {
  try {
    const trigger = String(req.body?.trigger || "manual");
    const result = await runDigest({ trigger });
    res.json(result);
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

/** HTTP stand-in for MCP tool digest_get_last */
app.post("/api/mcp/digest_get_last", (_req, res) => {
  res.json({ ok: true, last: getLastDigest(), status: digestStatus() });
});

app.post("/api/mcp/digest_run_now", async (req, res) => {
  try {
    const result = await runDigest({ trigger: "mcp" });
    res.json(result);
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`Day 18 UI: http://127.0.0.1:${PORT}`);
});
