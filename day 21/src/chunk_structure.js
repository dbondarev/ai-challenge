/**
 * Structure-aware chunking: split by Часть / heading lines, then sub-chunk large sections.
 */
import { chunkFixed } from "./chunk_fixed.js";

export function chunkStructure(doc, opts = {}) {
  const maxChunk = Number(
    opts.structMaxChunk || process.env.STRUCT_MAX_CHUNK || 1200
  );
  const text = doc.text || "";
  const source = doc.source || doc.source_abs || "unknown";
  const title = doc.title || source;

  const sections = splitSections(text);
  const chunks = [];
  let index = 0;

  for (const sec of sections) {
    const body = sec.text.trim();
    if (body.length < 40) continue;

    if (body.length <= maxChunk) {
      chunks.push({
        chunk_id: `struct-${String(index).padStart(5, "0")}`,
        strategy: "structure",
        source,
        title,
        section: sec.name,
        chunk_index: index,
        char_start: sec.start,
        char_end: sec.end,
        text: body,
      });
      index += 1;
      continue;
    }

    // Sub-chunk inside section without crossing section boundaries
    const subDoc = {
      text: body,
      source,
      title,
    };
    const sub = chunkFixed(subDoc, {
      chunkSize: Math.min(800, maxChunk),
      chunkOverlap: 100,
    });
    for (const s of sub) {
      chunks.push({
        chunk_id: `struct-${String(index).padStart(5, "0")}`,
        strategy: "structure",
        source,
        title,
        section: sec.name,
        chunk_index: index,
        char_start: sec.start + s.char_start,
        char_end: sec.start + s.char_end,
        text: s.text,
      });
      index += 1;
    }
  }

  return chunks;
}

function splitSections(text) {
  const lines = text.split("\n");
  const breaks = []; // { lineIndex, name, charOffset }

  let offset = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    const prev = (lines[i - 1] || "").trim();
    const next = (lines[i + 1] || "").trim();

    if (isSectionHeading(trimmed, prev, next)) {
      breaks.push({ lineIndex: i, name: trimmed, charOffset: offset });
    }
    offset += line.length + 1;
  }

  if (!breaks.length) {
    return [{ name: "body", start: 0, end: text.length, text }];
  }

  // Ensure we capture preamble before first heading
  const sections = [];
  if (breaks[0].charOffset > 0) {
    const preamble = text.slice(0, breaks[0].charOffset);
    if (preamble.trim().length >= 40) {
      sections.push({
        name: "preamble",
        start: 0,
        end: breaks[0].charOffset,
        text: preamble,
      });
    }
  }

  for (let i = 0; i < breaks.length; i++) {
    const start = breaks[i].charOffset;
    const end =
      i + 1 < breaks.length ? breaks[i + 1].charOffset : text.length;
    sections.push({
      name: breaks[i].name,
      start,
      end,
      text: text.slice(start, end),
    });
  }
  return sections;
}

function isSectionHeading(trimmed, prev, next) {
  if (!trimmed) return false;
  if (/^Часть\b/i.test(trimmed)) return true;
  if (trimmed.length < 3 || trimmed.length > 80) return false;
  if (/^[•©]/.test(trimmed)) return false;
  if (/^\d+[\.\)]\s/.test(trimmed) && trimmed.length > 60) return false;
  // Heading-like: short, not ending with sentence punct, blank neighbors
  const blankNeighbor = !prev || !next;
  if (blankNeighbor && !/[.!?…,:;]$/.test(trimmed)) {
    // Avoid pure list bullets leftovers
    if (/^[-–—]/.test(trimmed)) return false;
    return true;
  }
  return false;
}
