import OpenAI from "openai";

import { fetchRecentMail } from "./mail.js";
import { appendDigest, getLastDigest } from "./store.js";
import { sendTelegramMessage } from "./telegram.js";

const TZ = "America/Chicago";

let running = false;

export function isDigestRunning() {
  return running;
}

async function summarize(messages, hours) {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!apiKey) {
    return fallbackSummary(messages, hours);
  }
  const model = (process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
  const openai = new OpenAI({ apiKey });
  const payload = messages.slice(0, 40).map((m) => ({
    subject: m.subject,
    from: m.from,
    at: m.receivedDateTime,
    preview: m.bodyPreview,
  }));

  const completion = await openai.chat.completions.create({
    model,
    messages: [
      {
        role: "system",
        content:
          "You write a short Russian morning email digest for Austin timezone. " +
          "Include: count, notable senders/topics, items that may need action. " +
          "Be concise (max ~1200 chars). No markdown tables. If zero messages, say it was a quiet period.",
      },
      {
        role: "user",
        content:
          `Window: last ${hours}h. Messages JSON:\n` +
          JSON.stringify(payload, null, 2),
      },
    ],
  });
  return (completion.choices[0]?.message?.content || "").trim() || fallbackSummary(messages, hours);
}

function fallbackSummary(messages, hours) {
  if (!messages.length) {
    return `Сводка почты (последние ${hours} ч.): писем нет. Тихий период.`;
  }
  const lines = messages.slice(0, 12).map((m, i) => {
    return `${i + 1}. ${m.from} — ${m.subject}`;
  });
  return (
    `Сводка почты (последние ${hours} ч.): ${messages.length} писем.\n` +
    lines.join("\n")
  );
}

/**
 * Full digest pipeline: mail -> summary -> store -> telegram.
 */
export async function runDigest({ trigger = "manual" } = {}) {
  if (running) {
    throw new Error("Digest already running");
  }
  running = true;
  const hours = Math.min(Math.max(Number(process.env.DIGEST_HOURS || 24) || 24, 1), 72);
  const top = Math.min(Math.max(Number(process.env.DIGEST_TOP || 30) || 30, 1), 50);
  const started = new Date().toISOString();

  try {
    const mail = await fetchRecentMail({ hours, top });
    const summary = await summarize(mail.messages, hours);
    const header =
      `Mail digest (${TZ})\n` +
      `trigger=${trigger} · ${mail.count} msgs · last ${hours}h\n` +
      `---\n`;
    const fullText = header + summary;

    const telegram = await sendTelegramMessage(fullText);

    const entry = {
      at: started,
      finished_at: new Date().toISOString(),
      trigger,
      timezone: TZ,
      hours,
      mail_count: mail.count,
      summary,
      telegram: {
        ok: telegram.ok,
        skipped: telegram.skipped || false,
        error: telegram.error || null,
        message_id: telegram.message_id || null,
      },
      raw_preview: mail.messages.slice(0, 8),
    };
    appendDigest(entry);

    return {
      ok: true,
      ...entry,
      telegram_error: telegram.ok ? null : telegram.error,
    };
  } finally {
    running = false;
  }
}

export function digestStatus() {
  const last = getLastDigest();
  return {
    timezone: TZ,
    cron: "0 6 * * *",
    cron_enabled: String(process.env.DIGEST_CRON_ENABLED || "true").toLowerCase() !== "false",
    running,
    last,
  };
}
