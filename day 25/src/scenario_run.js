import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";

import { DAY25_ROOT } from "./bridge.js";
import { handleTurn } from "./chat.js";
import { createSession } from "./session_store.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
dotenv.config({ path: resolve(ROOT, ".env") });

/**
 * Two long scenarios (12 user messages each) on Bailey book.
 */
export const SCENARIOS = [
  {
    id: "A_components",
    title: "Три компонента → углубление",
    goal_keys: ["время", "энерг", "вниман", "компонент", "продуктив"],
    messages: [
      "Хочу разобраться в трёх компонентах продуктивности по Бэйли. Это моя цель.",
      "Какие именно три компонента он выделяет?",
      "Как связаны время и продуктивность в его определении?",
      "Что автор пишет про энергию — как её поддерживать?",
      "Уточнение: меня интересует ещё и внимание, не только время.",
      "Что говорится про мультизадачность и внимание?",
      "Есть ли связь между сном и энергией в книге?",
      "Ограничение: не углубляйся в маркетинг/продажи книги, только практика.",
      "Как автор предлагает управлять вниманием на практике?",
      "Собери кратко: время, энергия, внимание — по одному тезису.",
      "Что я уже уточнил? Напомни цель диалога своими словами.",
      "Дай короткий план на неделю из этих трёх компонентов со ссылками на книгу.",
    ],
  },
  {
    id: "B_goal_shift",
    title: "Смена цели mid-dialog",
    goal_keys: ["вниман"],
    messages: [
      "Расскажи про «точку продуктивности» — с этого начнём.",
      "Как автор раскладывает 24 часа суток?",
      "Ок, меняю цель: теперь хочу разобраться ТОЛЬКО во внимании, не в общей точке продуктивности.",
      "Зафиксируй ограничение: только про внимание и фокус.",
      "Что Бэйли пишет про управление вниманием?",
      "Как отвлечения связаны с продуктивностью внимания?",
      "Есть ли советы про однозадачность?",
      "Не возвращайся к разбивке суток — только внимание.",
      "Какие практики внимания автор рекомендует?",
      "Сравни кратко: внимание vs энергия — но ответ держи в рамках внимания.",
      "Напомни мою текущую цель и ограничение.",
      "Итог: 3 шага про внимание из книги.",
    ],
  },
];

function norm(s) {
  return String(s || "").toLowerCase().replace(/ё/g, "е");
}

function goalHolds(goal, keys) {
  const g = norm(goal);
  return (keys || []).some((k) => g.includes(norm(k)));
}

async function runScenario(scenario) {
  const session = createSession();
  const turns = [];
  let userCount = 0;

  for (const msg of scenario.messages) {
    userCount += 1;
    process.stderr.write(`[${scenario.id}] turn ${userCount}/${scenario.messages.length}…\n`);
    const result = await handleTurn({ sessionId: session.id, message: msg });
    const sourcesOk =
      Boolean(result.refuse) || (result.sources || []).length >= 1;
    const goalNonEmpty =
      userCount < 2 || Boolean(String(result.task_state?.goal || "").trim());

    turns.push({
      n: userCount,
      user: msg,
      reply_preview: String(result.reply || "").slice(0, 220),
      refuse: result.refuse,
      sources_count: (result.sources || []).length,
      sources_ok: sourcesOk,
      goal: result.task_state?.goal || "",
      constraints: result.task_state?.constraints || [],
      goal_nonempty: goalNonEmpty,
      task_state: result.task_state,
    });
  }

  const last3 = turns.slice(-3);
  const goal_held = last3.every((t) => goalHolds(t.goal, scenario.goal_keys));
  const all_sources_ok = turns.every((t) => t.sources_ok);
  const all_goal_nonempty = turns.every((t) => t.goal_nonempty);

  return {
    id: scenario.id,
    title: scenario.title,
    session_id: session.id,
    turns,
    checks: {
      all_sources_ok,
      all_goal_nonempty,
      goal_held_last3: goal_held,
      passed: all_sources_ok && all_goal_nonempty && goal_held,
    },
  };
}

export async function runAllScenarios() {
  const results = [];
  for (const sc of SCENARIOS) {
    results.push(await runScenario(sc));
  }
  const summary = {
    scenarios: results.length,
    passed: results.filter((r) => r.checks.passed).length,
  };
  const report = {
    built_at: new Date().toISOString(),
    summary,
    results,
  };

  const outDir = resolve(DAY25_ROOT, "data/reports");
  mkdirSync(outDir, { recursive: true });
  writeFileSync(resolve(outDir, "scenarios.json"), JSON.stringify(report, null, 2), "utf8");

  const md = [
    "# Day 25 — Scenario report",
    "",
    `Built: ${report.built_at}`,
    "",
    `Passed: ${summary.passed}/${summary.scenarios}`,
    "",
  ];
  for (const r of results) {
    md.push(`## ${r.id} — ${r.title}`);
    md.push("");
    md.push(
      `passed=${r.checks.passed} sources_ok=${r.checks.all_sources_ok} ` +
        `goal_nonempty=${r.checks.all_goal_nonempty} goal_held_last3=${r.checks.goal_held_last3}`
    );
    md.push("");
    md.push(`Final goal: ${r.turns.at(-1)?.goal || "—"}`);
    md.push("");
    for (const t of r.turns) {
      md.push(
        `- #${t.n} sources=${t.sources_count} refuse=${t.refuse} | ${t.user.slice(0, 80)}`
      );
    }
    md.push("");
  }
  writeFileSync(resolve(outDir, "scenarios.md"), md.join("\n"), "utf8");
  return report;
}

const isMain =
  process.argv[1] &&
  fileURLToPath(import.meta.url) === resolve(process.argv[1]);

if (isMain) {
  runAllScenarios()
    .then((r) => {
      console.log(JSON.stringify(r.summary, null, 2));
      for (const sc of r.results) {
        console.log(sc.id, sc.checks);
      }
      console.log("Wrote data/reports/scenarios.md");
      if (r.summary.passed < r.summary.scenarios) process.exitCode = 1;
    })
    .catch((e) => {
      console.error(e);
      process.exit(1);
    });
}
