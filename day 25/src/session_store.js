import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { DAY25_ROOT } from "./bridge.js";

const SESSIONS_DIR = resolve(DAY25_ROOT, "data/sessions");

function emptyTaskState() {
  return {
    goal: "",
    clarifications: [],
    constraints: [],
    terms: {},
  };
}

export function createSession() {
  mkdirSync(SESSIONS_DIR, { recursive: true });
  const id = randomUUID();
  const session = {
    id,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    task_state: emptyTaskState(),
    messages: [],
  };
  saveSession(session);
  return session;
}

export function sessionPath(id) {
  return resolve(SESSIONS_DIR, `${id}.json`);
}

export function loadSession(id) {
  const p = sessionPath(id);
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, "utf8"));
}

export function saveSession(session) {
  mkdirSync(SESSIONS_DIR, { recursive: true });
  session.updated_at = new Date().toISOString();
  writeFileSync(sessionPath(session.id), JSON.stringify(session, null, 2), "utf8");
  return session;
}

export function deleteSession(id) {
  const p = sessionPath(id);
  if (existsSync(p)) unlinkSync(p);
  return true;
}

export function getOrCreateSession(sessionId) {
  if (sessionId) {
    const existing = loadSession(sessionId);
    if (existing) return existing;
  }
  return createSession();
}

export { emptyTaskState, SESSIONS_DIR };
