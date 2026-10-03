import {
  createHash,
} from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  readdirSync,
  statSync,
  writeFileSync,
  rmSync,
} from "node:fs";
import { basename, extname, resolve } from "node:path";

import { DAY21_ROOT } from "./load_text.js";

const INDEX_DIR = resolve(DAY21_ROOT, "data/index");
const CATALOG_PATH = resolve(INDEX_DIR, "catalog.json");
const INBOX_DIR = resolve(DAY21_ROOT, "data/inbox");
const BOOKS_DIR = resolve(DAY21_ROOT, "../../Books");

const TEXT_EXTS = new Set([".txt", ".md", ".text", ".markdown"]);

export function makeDocId(filePath) {
  const base = basename(filePath, extname(filePath))
    .replace(/[^\wа-яА-ЯёЁ\-]+/gi, "_")
    .replace(/_+/g, "_")
    .slice(0, 48)
    .replace(/^_|_$/g, "") || "doc";
  const hash = createHash("sha1").update(resolve(filePath)).digest("hex").slice(0, 8);
  return `${base}-${hash}`;
}

function emptyCatalog() {
  return { version: 1, active_id: null, docs: {} };
}

export function loadCatalog() {
  mkdirSync(INDEX_DIR, { recursive: true });
  migrateLegacyIndexes();
  if (!existsSync(CATALOG_PATH)) {
    const cat = emptyCatalog();
    saveCatalog(cat);
    return cat;
  }
  try {
    const cat = JSON.parse(readFileSync(CATALOG_PATH, "utf8"));
    if (!cat.docs) cat.docs = {};
    return cat;
  } catch {
    return emptyCatalog();
  }
}

export function saveCatalog(cat) {
  mkdirSync(INDEX_DIR, { recursive: true });
  writeFileSync(CATALOG_PATH, JSON.stringify(cat, null, 2), "utf8");
}

/** Move old flat fixed.json/structure.json into a doc folder once. */
function migrateLegacyIndexes() {
  const legacyFixed = resolve(INDEX_DIR, "fixed.json");
  const legacyStruct = resolve(INDEX_DIR, "structure.json");
  if (!existsSync(legacyFixed) && !existsSync(legacyStruct)) return;

  let sourceAbs = null;
  let title = "Legacy index";
  try {
    if (existsSync(legacyFixed)) {
      const j = JSON.parse(readFileSync(legacyFixed, "utf8"));
      sourceAbs = j.meta?.source_abs || j.meta?.source;
      title = j.meta?.title || title;
    }
  } catch {
    /* */
  }
  if (!sourceAbs || !existsSync(String(sourceAbs))) {
    sourceAbs = resolve(BOOKS_DIR, "Byeyili_K._Moyi_Produktivnyiyi_God_K.txt");
  }
  const id = makeDocId(sourceAbs);
  const dir = resolve(INDEX_DIR, id);
  mkdirSync(dir, { recursive: true });
  if (existsSync(legacyFixed)) {
    renameSync(legacyFixed, resolve(dir, "fixed.json"));
  }
  if (existsSync(legacyStruct)) {
    renameSync(legacyStruct, resolve(dir, "structure.json"));
  }

  let cat = emptyCatalog();
  if (existsSync(CATALOG_PATH)) {
    try {
      cat = JSON.parse(readFileSync(CATALOG_PATH, "utf8"));
    } catch {
      cat = emptyCatalog();
    }
  }
  if (!cat.docs) cat.docs = {};
  cat.docs[id] = {
    id,
    path: sourceAbs,
    source: basename(sourceAbs),
    title,
    built_at: new Date().toISOString(),
    strategies: {
      fixed: existsSync(resolve(dir, "fixed.json")),
      structure: existsSync(resolve(dir, "structure.json")),
    },
  };
  if (!cat.active_id) cat.active_id = id;
  saveCatalog(cat);
}

export function docDir(docId) {
  return resolve(INDEX_DIR, docId);
}

export function upsertDoc(entry) {
  const cat = loadCatalog();
  cat.docs[entry.id] = { ...cat.docs[entry.id], ...entry };
  if (!cat.active_id) cat.active_id = entry.id;
  saveCatalog(cat);
  return cat.docs[entry.id];
}

export function setActiveDoc(docId) {
  const cat = loadCatalog();
  if (!cat.docs[docId]) throw new Error(`Unknown doc id: ${docId}`);
  cat.active_id = docId;
  saveCatalog(cat);
  return cat;
}

export function getActiveDoc() {
  const cat = loadCatalog();
  if (!cat.active_id || !cat.docs[cat.active_id]) return null;
  return cat.docs[cat.active_id];
}

export function listDocs() {
  const cat = loadCatalog();
  return {
    active_id: cat.active_id,
    docs: Object.values(cat.docs).sort((a, b) =>
      String(b.built_at || "").localeCompare(String(a.built_at || ""))
    ),
  };
}

export function removeDoc(docId) {
  const cat = loadCatalog();
  if (!cat.docs[docId]) throw new Error(`Unknown doc id: ${docId}`);
  delete cat.docs[docId];
  if (cat.active_id === docId) {
    const ids = Object.keys(cat.docs);
    cat.active_id = ids[0] || null;
  }
  saveCatalog(cat);
  const dir = docDir(docId);
  if (existsSync(dir)) {
    rmSync(dir, { recursive: true, force: true });
  }
  return cat;
}

export function listBrowsableFiles(rootKey = "books") {
  const root =
    rootKey === "inbox"
      ? INBOX_DIR
      : rootKey === "books"
        ? BOOKS_DIR
        : null;
  if (!root || !existsSync(root)) {
    return { root: root || rootKey, files: [] };
  }
  const files = [];
  for (const name of readdirSync(root)) {
    const full = resolve(root, name);
    let st;
    try {
      st = statSync(full);
    } catch {
      continue;
    }
    if (!st.isFile()) continue;
    const ext = extname(name).toLowerCase();
    if (!TEXT_EXTS.has(ext)) continue;
    files.push({
      name,
      path: full,
      bytes: st.size,
      mtime: st.mtime.toISOString(),
    });
  }
  files.sort((a, b) => a.name.localeCompare(b.name));
  return { root, files };
}

export function isAllowedTextPath(filePath) {
  const ext = extname(filePath).toLowerCase();
  return TEXT_EXTS.has(ext);
}

export { INDEX_DIR, CATALOG_PATH, INBOX_DIR, BOOKS_DIR, TEXT_EXTS };
