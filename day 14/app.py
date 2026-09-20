from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from agent import ALLOWED_MODELS, CATEGORIES, Agent, ContextOverflowError

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
_agent: Optional[Agent] = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        _agent = Agent(api_key=api_key, base_dir=BASE_DIR)
    return _agent


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/history")
def history():
    try:
        return jsonify(get_agent().snapshot())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    try:
        agent = get_agent()
        if data.get("role") is not None:
            agent.set_role(data.get("role") or "")
        model = (data.get("model") or "").strip()
        if model:
            agent.set_model(model)
        if data.get("context_limit") not in (None, ""):
            agent.set_context_limit(int(data["context_limit"]))
        if data.get("window_size") not in (None, ""):
            agent.set_window_size(int(data["window_size"]))
        if not prompt:
            return jsonify({"error": "Empty prompt"}), 400
        return jsonify(agent.reply(prompt))
    except ContextOverflowError as exc:
        return jsonify({"error": str(exc), "tokens": getattr(exc, "tokens", None)}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/invariants")
def invariants_list():
    try:
        agent = get_agent()
        return jsonify(
            {
                "items": agent.invariants.list_all(),
                "categories": list(CATEGORIES),
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/invariants")
def invariants_upsert():
    data = request.get_json(silent=True) or {}
    try:
        agent = get_agent()
        item = agent.invariants.upsert(
            item_id=(data.get("id") or None),
            category=str(data.get("category") or "tech_decision"),
            statement=str(data.get("statement") or ""),
            active=bool(data.get("active", True)),
        )
        return jsonify({"ok": True, "item": item, "state": agent.snapshot()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/invariants/toggle")
def invariants_toggle():
    data = request.get_json(silent=True) or {}
    try:
        agent = get_agent()
        active = data.get("active")
        item = agent.invariants.toggle(
            str(data.get("id") or ""),
            None if active is None else bool(active),
        )
        return jsonify({"ok": True, "item": item, "state": agent.snapshot()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/invariants/delete")
def invariants_delete():
    data = request.get_json(silent=True) or {}
    try:
        agent = get_agent()
        agent.invariants.delete(str(data.get("id") or ""))
        return jsonify({"ok": True, "state": agent.snapshot()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/invariants/reset-demo")
def invariants_reset_demo():
    try:
        agent = get_agent()
        items = agent.invariants.reset_demo()
        return jsonify({"ok": True, "items": items, "state": agent.snapshot()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/dialog/clear")
def dialog_clear():
    try:
        agent = get_agent()
        agent.clear_dialog()
        return jsonify({"ok": True, "state": agent.snapshot()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/reset")
def reset():
    try:
        agent = get_agent()
        agent.reset()
        return jsonify({"ok": True, "state": agent.snapshot()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/models")
def models():
    return jsonify({"models": sorted(ALLOWED_MODELS)})
