import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import dotenv from "dotenv";

const DAY24_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(DAY24_ROOT, ".env") });

export function resolveDay21Root() {
  const fromEnv = (process.env.DAY21_ROOT || "").trim();
  return fromEnv
    ? resolve(DAY24_ROOT, fromEnv)
    : resolve(DAY24_ROOT, "../day 21");
}

export function resolveDay22Root() {
  const fromEnv = (process.env.DAY22_ROOT || "").trim();
  return fromEnv
    ? resolve(DAY24_ROOT, fromEnv)
    : resolve(DAY24_ROOT, "../day 22");
}

export function resolveDay23Root() {
  const fromEnv = (process.env.DAY23_ROOT || "").trim();
  return fromEnv
    ? resolve(DAY24_ROOT, fromEnv)
    : resolve(DAY24_ROOT, "../day 23");
}

const DAY21_ROOT = resolveDay21Root();
const DAY22_ROOT = resolveDay22Root();
const DAY23_ROOT = resolveDay23Root();
dotenv.config({ path: resolve(DAY21_ROOT, ".env") });
dotenv.config({ path: resolve(DAY22_ROOT, ".env") });
dotenv.config({ path: resolve(DAY23_ROOT, ".env") });
dotenv.config({ path: resolve(DAY24_ROOT, ".env") });

async function importFrom(root, rel) {
  return import(pathToFileURL(resolve(root, "src", rel)).href);
}

let _d21 = null;
let _d22eval = null;
let _d23 = null;

export async function day21() {
  if (_d21) return _d21;
  const [docs_db, index_store, embed, search] = await Promise.all([
    importFrom(DAY21_ROOT, "docs_db.js"),
    importFrom(DAY21_ROOT, "index_store.js"),
    importFrom(DAY21_ROOT, "embed.js"),
    importFrom(DAY21_ROOT, "search.js"),
  ]);
  _d21 = { docs_db, index_store, embed, search, DAY21_ROOT };
  return _d21;
}

export async function day22EvalSet() {
  if (_d22eval) return _d22eval;
  _d22eval = await importFrom(DAY22_ROOT, "eval_set.js");
  return _d22eval;
}

export async function day23() {
  if (_d23) return _d23;
  const [rewrite, retrieve, filter_rerank] = await Promise.all([
    importFrom(DAY23_ROOT, "rewrite.js"),
    importFrom(DAY23_ROOT, "retrieve.js"),
    importFrom(DAY23_ROOT, "filter_rerank.js"),
  ]);
  _d23 = { rewrite, retrieve, filter_rerank, DAY23_ROOT };
  return _d23;
}

export { DAY24_ROOT, DAY21_ROOT, DAY22_ROOT, DAY23_ROOT };
