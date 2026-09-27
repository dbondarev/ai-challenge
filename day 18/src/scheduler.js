import cron from "node-cron";

import { runDigest } from "./digest.js";

const TZ = "America/Chicago";
const EXPR = "0 6 * * *";

let task = null;
let lastCronError = null;
let lastCronAt = null;

export function startScheduler() {
  const enabled = String(process.env.DIGEST_CRON_ENABLED || "true").toLowerCase() !== "false";
  if (!enabled) {
    return { started: false, reason: "DIGEST_CRON_ENABLED=false" };
  }
  if (task) {
    return { started: true, already: true, expression: EXPR, timezone: TZ };
  }
  if (!cron.validate(EXPR)) {
    throw new Error(`Invalid cron: ${EXPR}`);
  }
  task = cron.schedule(
    EXPR,
    async () => {
      lastCronAt = new Date().toISOString();
      try {
        await runDigest({ trigger: "cron" });
        lastCronError = null;
      } catch (err) {
        lastCronError = err instanceof Error ? err.message : String(err);
        console.error("[day18 cron]", lastCronError);
      }
    },
    { timezone: TZ }
  );
  return { started: true, expression: EXPR, timezone: TZ };
}

export function stopScheduler() {
  if (task) {
    task.stop();
    task = null;
  }
}

export function schedulerInfo() {
  const enabled = String(process.env.DIGEST_CRON_ENABLED || "true").toLowerCase() !== "false";
  return {
    enabled,
    running: Boolean(task),
    expression: EXPR,
    timezone: TZ,
    description: "Every day at 06:00 America/Chicago (Austin)",
    last_cron_at: lastCronAt,
    last_cron_error: lastCronError,
  };
}
