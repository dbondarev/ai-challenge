/**
 * Send a text message via Telegram Bot API.
 */
export async function sendTelegramMessage(text) {
  const token = (process.env.TELEGRAM_BOT_TOKEN || "").trim();
  const chatId = (process.env.TELEGRAM_CHAT_ID || "").trim();
  if (!token || !chatId) {
    return {
      ok: false,
      skipped: true,
      error: "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing",
    };
  }

  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const body = {
    chat_id: chatId,
    text: String(text || "").slice(0, 4000),
    disable_web_page_preview: true,
  };

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) {
    return {
      ok: false,
      skipped: false,
      error: data.description || res.statusText || "Telegram API error",
      raw: data,
    };
  }
  return { ok: true, skipped: false, message_id: data.result?.message_id };
}
