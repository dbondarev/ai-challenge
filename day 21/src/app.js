import { existsSync, mkdirSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";
import express from "express";
import multer from "multer";

import { buildAll } from "./build.js";
import { compareIndexes } from "./compare.js";
import {
  INBOX_DIR,
  getActiveDoc,
  isAllowedTextPath,
  listBrowsableFiles,
  listDocs,
  removeDoc,
  setActiveDoc,
} from "./docs_db.js";
import { indexStatus } from "./index_store.js";
import { resolveBookPath } from "./load_text.js";
import { searchIndex } from "./search.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

mkdirSync(INBOX_DIR, { recursive: true });

const upload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => cb(null, INBOX_DIR),
    filename: (_req, file, cb) => {
      const safe = basename(file.originalname).replace(/[^\w.\-а-яА-ЯёЁ]+/gi, "_");
      cb(null, `${Date.now()}-${safe}`);
    },
  }),
  limits: { fileSize: 40 * 1024 * 1024 },
});

const app = express();
const PORT = Number(process.env.PORT || 5020);

app.use(express.json({ limit: "2mb" }));
app.use(express.static(resolve(ROOT, "templates")));

let building = false;

app.get("/", (_req, res) => {
  res.sendFile(resolve(ROOT, "templates/index.html"));
});

app.get("/api/status", (_req, res) => {
  const docs = listDocs();
  const active = getActiveDoc();
  res.json({
    ok: true,
    port: PORT,
    has_openai: Boolean((process.env.OPENAI_API_KEY || "").trim()),
    embedding_model: (
      process.env.EMBEDDING_MODEL || "text-embedding-3-small"
    ).trim(),
    default_book: resolveBookPath(),
    active,
    docs: docs.docs,
    active_id: docs.active_id,
    indexes: indexStatus(docs.active_id),
    building,
  });
});

app.get("/api/docs", (_req, res) => {
  res.json({ ok: true, ...listDocs() });
});

app.post("/api/docs/select", (req, res) => {
  try {
    const id = String(req.body?.id || "").trim();
    if (!id) return res.status(400).json({ ok: false, error: "id required" });
    const cat = setActiveDoc(id);
    res.json({
      ok: true,
      active_id: cat.active_id,
      active: cat.docs[cat.active_id],
      indexes: indexStatus(cat.active_id),
    });
  } catch (err) {
    res.status(400).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.delete("/api/docs/:id", (req, res) => {
  try {
    const cat = removeDoc(req.params.id);
    res.json({ ok: true, ...listDocs(), active_id: cat.active_id });
  } catch (err) {
    res.status(400).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.get("/api/browse", (req, res) => {
  const root = String(req.query.root || "books");
  res.json({ ok: true, ...listBrowsableFiles(root) });
});

app.post("/api/upload", upload.single("file"), (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ ok: false, error: "file required" });
    }
    if (!isAllowedTextPath(req.file.path)) {
      return res.status(400).json({
        ok: false,
        error: "Only .txt / .md text files are supported",
      });
    }
    res.json({
      ok: true,
      path: req.file.path,
      name: req.file.filename,
      bytes: req.file.size,
    });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.post("/api/build", async (req, res) => {
  if (building) {
    return res.status(409).json({ ok: false, error: "build already running" });
  }
  building = true;
  try {
    const smoke = Boolean(req.body?.smoke);
    let path = String(req.body?.path || "").trim();
    if (!path && req.body?.use_active) {
      const active = getActiveDoc();
      path = active?.path || "";
    }
    if (!path) path = resolveBookPath();
    if (!existsSync(path)) {
      return res.status(400).json({ ok: false, error: `File not found: ${path}` });
    }
    if (!isAllowedTextPath(path)) {
      return res.status(400).json({
        ok: false,
        error: "Only .txt / .md text files are supported for indexing",
      });
    }
    const result = await buildAll({ smoke, path });
    res.json(result);
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  } finally {
    building = false;
  }
});

app.get("/api/compare", (req, res) => {
  try {
    const docId = String(req.query.docId || "").trim() || undefined;
    const report = compareIndexes(docId);
    res.json({ ok: true, ...report });
  } catch (err) {
    res.status(404).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.post("/api/search", async (req, res) => {
  try {
    const query = String(req.body?.query || "").trim();
    const strategy = String(req.body?.strategy || "structure");
    const topK = Number(req.body?.topK || 5);
    const docId = String(req.body?.docId || "").trim() || undefined;
    if (!query) {
      return res.status(400).json({ ok: false, error: "query required" });
    }
    if (!["fixed", "structure"].includes(strategy)) {
      return res
        .status(400)
        .json({ ok: false, error: "strategy must be fixed|structure" });
    }
    const result = await searchIndex(strategy, query, topK, docId);
    res.json({ ok: true, ...result });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`[day21] http://127.0.0.1:${PORT}`);
});
