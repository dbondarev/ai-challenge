/**
 * Fixed-size sliding window chunking with soft boundary snap.
 */
export function chunkFixed(doc, opts = {}) {
  const size = Number(opts.chunkSize || process.env.CHUNK_SIZE || 800);
  const overlap = Number(opts.chunkOverlap || process.env.CHUNK_OVERLAP || 120);
  const text = doc.text || "";
  const source = doc.source || doc.source_abs || "unknown";
  const title = doc.title || source;

  if (size < 50) throw new Error("CHUNK_SIZE too small");
  if (overlap >= size) throw new Error("CHUNK_OVERLAP must be < CHUNK_SIZE");

  const headings = scanHeadings(text);
  const chunks = [];
  let start = 0;
  let index = 0;

  while (start < text.length) {
    let end = Math.min(start + size, text.length);
    if (end < text.length) {
      end = snapBoundary(text, end, 40);
    }
    if (end <= start) end = Math.min(start + size, text.length);

    const slice = text.slice(start, end).trim();
    if (slice.length >= 40) {
      const section = nearestHeading(headings, start) || "body";
      chunks.push({
        chunk_id: `fixed-${String(index).padStart(5, "0")}`,
        strategy: "fixed",
        source,
        title,
        section,
        chunk_index: index,
        char_start: start,
        char_end: end,
        text: slice,
      });
      index += 1;
    }

    if (end >= text.length) break;
    const next = end - overlap;
    start = next <= start ? end : next;
  }

  return chunks;
}

function snapBoundary(text, end, window) {
  const from = Math.max(0, end - window);
  const region = text.slice(from, end);
  const nl = region.lastIndexOf("\n");
  if (nl >= 0) return from + nl + 1;
  const sp = region.lastIndexOf(" ");
  if (sp >= 0) return from + sp + 1;
  return end;
}

function scanHeadings(text) {
  const lines = text.split("\n");
  const out = [];
  let offset = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    const next = (lines[i + 1] || "").trim();
    const prev = (lines[i - 1] || "").trim();
    if (isHeadingLine(trimmed, prev, next)) {
      out.push({ offset, title: trimmed });
    }
    offset += line.length + 1;
  }
  return out;
}

function isHeadingLine(trimmed, prev, next) {
  if (!trimmed) return false;
  if (trimmed.length < 3 || trimmed.length > 80) return false;
  if (/^[•©\-\d]/.test(trimmed) && !/^Часть\b/i.test(trimmed)) return false;
  if (/^Часть\b/i.test(trimmed)) return true;
  // short line surrounded by blanks-ish (prev empty or next empty)
  if (!prev || !next) {
    if (!/[.!?…]$/.test(trimmed) && !trimmed.includes("  ")) return true;
  }
  return false;
}

function nearestHeading(headings, pos) {
  let best = null;
  for (const h of headings) {
    if (h.offset <= pos) best = h.title;
    else break;
  }
  return best;
}
