import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";
import express from "express";

import { listMcpTools, resolveServerLaunch } from "./mcp_client.js";

const DAY16_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(DAY16_ROOT, ".env") });

const app = express();
const PORT = Number(process.env.PORT || 5015);

app.use(express.json());
app.use(express.static(resolve(DAY16_ROOT, "templates")));

app.get("/", (_req, res) => {
  res.sendFile(resolve(DAY16_ROOT, "templates/index.html"));
});

app.get("/api/config", (_req, res) => {
  const launch = resolveServerLaunch();
  res.json({
    command: launch.command,
    args: launch.args,
    script: launch.serverScript,
    port: PORT,
  });
});

app.post("/api/tools", async (_req, res) => {
  try {
    const result = await listMcpTools();
    res.json(result);
  } catch (err) {
    res.status(500).json({
      ok: false,
      connected: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`Day 16 UI: http://127.0.0.1:${PORT}`);
});
