import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import dotenv from "dotenv";

const DAY22_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(DAY22_ROOT, ".env") });

export function resolveDay21Root() {
  const fromEnv = (process.env.DAY21_ROOT || "").trim();
  if (fromEnv) {
    return resolve(DAY22_ROOT, fromEnv);
  }
  return resolve(DAY22_ROOT, "../day 21");
}

const DAY21_ROOT = resolveDay21Root();
// Also load day21 env for embedding keys if day22 missing (already copied)
dotenv.config({ path: resolve(DAY21_ROOT, ".env") });

async function importDay21(rel) {
  const abs = resolve(DAY21_ROOT, "src", rel);
  return import(pathToFileURL(abs).href);
}

let _cache = null;

export async function day21() {
  if (_cache) return _cache;
  const [
    docs_db,
    index_store,
    embed,
    search,
  ] = await Promise.all([
    importDay21("docs_db.js"),
    importDay21("index_store.js"),
    importDay21("embed.js"),
    importDay21("search.js"),
  ]);
  _cache = { docs_db, index_store, embed, search, DAY21_ROOT };
  return _cache;
}

export { DAY22_ROOT, DAY21_ROOT };
