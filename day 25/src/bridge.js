import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import dotenv from "dotenv";

const DAY25_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(DAY25_ROOT, ".env") });

function resolveRoot(envKey, fallbackRel) {
  const fromEnv = (process.env[envKey] || "").trim();
  return fromEnv
    ? resolve(DAY25_ROOT, fromEnv)
    : resolve(DAY25_ROOT, fallbackRel);
}

const DAY21_ROOT = resolveRoot("DAY21_ROOT", "../day 21");
const DAY22_ROOT = resolveRoot("DAY22_ROOT", "../day 22");
const DAY23_ROOT = resolveRoot("DAY23_ROOT", "../day 23");
const DAY24_ROOT = resolveRoot("DAY24_ROOT", "../day 24");

dotenv.config({ path: resolve(DAY21_ROOT, ".env") });
dotenv.config({ path: resolve(DAY24_ROOT, ".env") });
dotenv.config({ path: resolve(DAY25_ROOT, ".env") });

async function importFrom(root, rel) {
  return import(pathToFileURL(resolve(root, "src", rel)).href);
}

let _d21 = null;
let _d24 = null;

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

export async function day24() {
  if (_d24) return _d24;
  const [grounded, validate] = await Promise.all([
    importFrom(DAY24_ROOT, "grounded.js"),
    importFrom(DAY24_ROOT, "validate.js"),
  ]);
  _d24 = { grounded, validate, DAY24_ROOT };
  return _d24;
}

export { DAY25_ROOT, DAY21_ROOT, DAY22_ROOT, DAY23_ROOT, DAY24_ROOT };
