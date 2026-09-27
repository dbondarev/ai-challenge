import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DATA_DIR = resolve(ROOT, "data");
const DIGESTS_PATH = resolve(DATA_DIR, "digests.json");

function ensure() {
  if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });
  if (!existsSync(DIGESTS_PATH)) {
    writeFileSync(DIGESTS_PATH, JSON.stringify({ digests: [] }, null, 2) + "\n", "utf8");
  }
}

export function loadDigests() {
  ensure();
  try {
    const raw = JSON.parse(readFileSync(DIGESTS_PATH, "utf8"));
    const digests = Array.isArray(raw.digests) ? raw.digests : [];
    return { digests };
  } catch {
    return { digests: [] };
  }
}

export function appendDigest(entry) {
  const data = loadDigests();
  data.digests.push(entry);
  // keep last 60
  if (data.digests.length > 60) data.digests = data.digests.slice(-60);
  writeFileSync(DIGESTS_PATH, JSON.stringify(data, null, 2) + "\n", "utf8");
  return entry;
}

export function getLastDigest() {
  const { digests } = loadDigests();
  return digests.length ? digests[digests.length - 1] : null;
}

export function listDigests(limit = 10) {
  const { digests } = loadDigests();
  return digests.slice(-Math.max(1, limit)).reverse();
}

export { DIGESTS_PATH, ROOT };
