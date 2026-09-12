from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from agent import ALLOWED_MODELS, STRATEGIES, Agent, ContextOverflowError, StrategyCompare

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
SCENARIO_PATH = BASE_DIR / "scenario.json"

app = Flask(__name__)

_agent: Optional[Agent] = None
_compare: Optional[StrategyCompare] = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        _agent = Agent(
            api_key=api_key,
            history_path=BASE_DIR / "history.json",
        )
    return _agent


def get_compare() -> StrategyCompare:
    global _compare
    if _compare is None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        _compare = StrategyCompare(
            api_key=api_key,
            history_path=BASE_DIR / "compare_history.json",
        )
    return _compare


def load_scenario() -> dict:
    raw = SCENARIO_PATH.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            return json.loads(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return json.loads(raw.decode("utf-8"))


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/compare")
def compare_page():
    try:
        scenario = load_scenario()
        role = scenario.get("role") or ""
    except Exception:
        role = ""
    return render_template("compare.html", scenario_role=role)


@app.get("/api/history")
def history():
    try:
        return jsonify(get_agent().snapshot())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    model = (data.get("model") or "").strip()
    role = data.get("role")
    context_limit = data.get("context_limit")
    strategy = (data.get("strategy") or "").strip()

    if not prompt:
        return jsonify({"error": "Prompt is empty"}), 400
    if model and model not in ALLOWED_MODELS:
        return jsonify({"error": f"Model not allowed: {model}"}), 400
    if strategy and strategy not in STRATEGIES:
        return jsonify({"error": f"Unknown strategy: {strategy}"}), 400

    try:
        agent = get_agent()
        if model:
            agent.set_model(model)
        if role is not None:
            agent.set_role(role)
        if context_limit is not None and context_limit != "":
            agent.set_context_limit(int(context_limit))
        if strategy:
            agent.set_strategy(strategy)
        if data.get("window_size") not in (None, ""):
            agent.set_window_size(int(data.get("window_size")))
        if data.get("facts_window") not in (None, ""):
            agent.set_facts_window(int(data.get("facts_window")))
        return jsonify(agent.reply(prompt))
    except ContextOverflowError as exc:
        return jsonify({"error": str(exc), "tokens": exc.tokens}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/facts")
def update_facts():
    data = request.get_json(silent=True) or {}
    try:
        agent = get_agent()
        agent.set_facts(data.get("facts") or {})
        return jsonify(agent.snapshot())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/facts/refresh")
def refresh_facts():
    try:
        return jsonify(get_agent().refresh_facts())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/checkpoint")
def checkpoint():
    try:
        return jsonify(get_agent().set_checkpoint())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/branch")
def branch_fork():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_agent().fork_branch(data.get("name") or ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/branch/switch")
def branch_switch():
    data = request.get_json(silent=True) or {}
    branch_id = (data.get("id") or "").strip()
    if not branch_id:
        return jsonify({"error": "id is required"}), 400
    try:
        return jsonify(get_agent().switch_branch(branch_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/reset")
def reset():
    try:
        agent = get_agent()
        agent.reset()
        return jsonify(agent.snapshot())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/compare/history")
def compare_history():
    try:
        return jsonify(get_compare().snapshot())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/compare/chat")
def compare_chat():
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    model = (data.get("model") or "").strip()
    role = data.get("role")
    context_limit = data.get("context_limit")

    if not prompt:
        return jsonify({"error": "Prompt is empty"}), 400
    if model and model not in ALLOWED_MODELS:
        return jsonify({"error": f"Model not allowed: {model}"}), 400

    try:
        cmp = get_compare()
        if model:
            cmp.set_model(model)
        if role is not None:
            cmp.set_role(role)
        if context_limit is not None and context_limit != "":
            cmp.set_context_limit(int(context_limit))
        if data.get("window_size") not in (None, ""):
            cmp.set_window_size(int(data.get("window_size")))
        if data.get("facts_window") not in (None, ""):
            cmp.set_facts_window(int(data.get("facts_window")))
        return jsonify(cmp.reply(prompt))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/compare/reset")
def compare_reset():
    try:
        cmp = get_compare()
        cmp.reset()
        return jsonify(cmp.snapshot())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/compare/scenario")
def compare_scenario():
    try:
        scenario = load_scenario()
        return jsonify(
            {
                "scenario": scenario,
                "total_steps": len(scenario.get("steps") or []),
                "state": get_compare().snapshot(),
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/compare/scenario/start")
def compare_scenario_start():
    """Reset compare state and apply scenario defaults (window_size=5, etc.)."""
    data = request.get_json(silent=True) or {}
    try:
        scenario = load_scenario()
        cmp = get_compare()
        cmp.reset()
        cmp.set_window_size(int(scenario.get("window_size") or 5))
        cmp.set_facts_window(int(scenario.get("facts_window") or 6))
        if scenario.get("role"):
            cmp.set_role(scenario["role"])
        model = (data.get("model") or "").strip()
        if model:
            cmp.set_model(model)
        if data.get("context_limit") not in (None, ""):
            cmp.set_context_limit(int(data["context_limit"]))
        cmp.scenario_step = 0
        cmp._save()
        return jsonify(
            {
                "ok": True,
                "total_steps": len(scenario.get("steps") or []),
                "scenario": scenario,
                "state": cmp.snapshot(),
            }
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/compare/scenario/step")
def compare_scenario_step():
    """Run the next scenario step (or step at index)."""
    data = request.get_json(silent=True) or {}
    try:
        scenario = load_scenario()
        steps = scenario.get("steps") or []
        cmp = get_compare()
        idx = data.get("index")
        if idx is None or idx == "":
            idx = cmp.scenario_step
        else:
            idx = int(idx)
        if idx < 0 or idx >= len(steps):
            return jsonify(
                {
                    "done": True,
                    "index": idx,
                    "total_steps": len(steps),
                    "state": cmp.snapshot(),
                }
            )

        step = steps[idx]
        action = step.get("action")
        label = step.get("label") or step.get("id") or f"step-{idx+1}"

        if action == "checkpoint":
            result = cmp.checkpoint()
        elif action == "fork":
            result = cmp.fork(step.get("names"))
        else:
            targets = step.get("targets") or ["sliding", "facts", "branching"]
            result = cmp.reply_targets(
                step.get("prompt") or "",
                targets=targets,
                label=label,
                step_id=step.get("id") or f"step-{idx+1}",
            )

        cmp.scenario_step = idx + 1
        cmp._save()
        return jsonify(
            {
                "done": cmp.scenario_step >= len(steps),
                "index": idx,
                "next_index": cmp.scenario_step,
                "total_steps": len(steps),
                "step": step,
                "result": result,
                "state": cmp.snapshot(),
            }
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True)
