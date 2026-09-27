import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";

import { listMcpTools } from "./mcp_client.js";

const DAY16_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(DAY16_ROOT, ".env") });

async function main() {
  console.log("Day 16 - MCP client -> m365-mail");
  console.log("Connecting...");
  const result = await listMcpTools();
  console.log("OK connected");
  console.log(`Server: ${result.server.command} ${result.server.args.join(" ")}`);
  console.log(`Tools: ${result.count}`);
  console.log("");
  result.tools.forEach((t, i) => {
    const desc = (t.description || "").replace(/\s+/g, " ").trim();
    console.log(`${i + 1}. ${t.name}`);
    if (desc) console.log(`   ${desc}`);
  });
}

main().catch((err) => {
  console.error("FAILED:", err.message || err);
  process.exit(1);
});
