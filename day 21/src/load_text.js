import { existsSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const DAY21_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const DEFAULT_BOOK = resolve(
  DAY21_ROOT,
  "../../Books/Byeyili_K._Moyi_Produktivnyiyi_God_K.txt"
);

/**
 * Load book text. Source is Windows-1251; convert to UTF-8 string in memory.
 * Does not modify the file under Books/.
 */
export function resolveBookPath() {
  const fromEnv = (process.env.BOOK_PATH || "").trim();
  return fromEnv || DEFAULT_BOOK;
}

export function loadText(bookPath = resolveBookPath()) {
  const path = resolve(bookPath);
  if (!existsSync(path)) {
    throw new Error(`Book not found: ${path}`);
  }
  const buf = readFileSync(path);
  let text;
  try {
    text = buf.toString("utf8");
    // Heuristic: if lots of replacement chars / mojibake, try cp1251
    const bad = (text.match(/\uFFFD/g) || []).length;
    if (bad > 10 || !/[\u0400-\u04FF]{20,}/.test(text)) {
      text = new TextDecoder("windows-1251").decode(buf);
    }
  } catch {
    text = new TextDecoder("windows-1251").decode(buf);
  }

  // Normalize newlines
  text = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const title = lines[0] || basename(path);
  const author = lines[1] && lines[1].length < 80 ? lines[1] : "";

  return {
    path,
    source: basename(path),
    source_abs: path,
    title,
    author,
    text,
    chars: text.length,
    lines: text.split("\n").length,
  };
}

export { DAY21_ROOT };
