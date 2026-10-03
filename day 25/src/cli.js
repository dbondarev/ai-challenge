import readline from "node:readline";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";

import { handleTurn } from "./chat.js";
import { createSession, loadSession } from "./session_store.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

let session = createSession();

function printState() {
  const s = loadSession(session.id) || session;
  console.log("\n--- task_state ---");
  console.log(JSON.stringify(s.task_state, null, 2));
  console.log("------------------\n");
}

async function main() {
  console.log(`Day 25 CLI chat. session=${session.id}`);
  console.log("Commands: /new  /state  /quit\n");

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  const ask = () => {
    rl.question("you> ", async (line) => {
      const text = String(line || "").trim();
      if (!text) return ask();
      if (text === "/quit" || text === "/exit") {
        rl.close();
        return;
      }
      if (text === "/new") {
        session = createSession();
        console.log(`new session=${session.id}`);
        return ask();
      }
      if (text === "/state") {
        printState();
        return ask();
      }
      try {
        const r = await handleTurn({ sessionId: session.id, message: text });
        session = { id: r.session_id };
        console.log(`\nassistant${r.refuse ? " [REFUSE]" : ""}>\n${r.reply}\n`);
        if (r.sources?.length) {
          console.log("sources:");
          for (const s of r.sources) {
            console.log(`  [${s.n}] ${s.section} (${s.chunk_id})`);
          }
        }
        console.log(`goal: ${r.task_state?.goal || "—"}\n`);
      } catch (e) {
        console.error("error:", e instanceof Error ? e.message : e);
      }
      ask();
    });
  };
  ask();
}

main();
