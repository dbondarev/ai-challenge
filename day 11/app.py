from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from agent import ALLOWED_MODELS, MODEL_CONTEXT_WINDOWS, Agent, ContextOverflowError

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
        agent = get_agent()
        if request.args.get("boot") in ("1", "true", "yes"):
            agent.boot_session()
        return jsonify(agent.snapshot())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/settings")
def settings():
    """Persist model / role / window immediately (model change must not wait for chat)."""
    data = request.get_json(silent=True) or {}
    try:
        agent = get_agent()
        model = (data.get("model") or "").strip()
        if model:
            agent.set_model(model)
        if data.get("role") is not None:
            agent.set_role(data.get("role") or "")
        if data.get("window_size") not in (None, ""):
            agent.set_window_size(int(data["window_size"]))
        return jsonify({"ok": True, "state": agent.snapshot()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
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
        if data.get("window_size") not in (None, ""):
            agent.set_window_size(int(data["window_size"]))
        if not prompt:
            return jsonify({"error": "Empty prompt"}), 400
        return jsonify(agent.reply(prompt))
    except ContextOverflowError as exc:
        return jsonify({"error": str(exc), "tokens": exc.tokens}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/memory/remember")
def memory_remember():
    data = request.get_json(silent=True) or {}
    layer = (data.get("layer") or "").strip()
    text = (data.get("text") or "").strip()
    index = data.get("index")
    try:
        agent = get_agent()
        if not text and index is not None:
            idx = int(index)
            if 0 <= idx < len(agent.short_term):
                msg = agent.short_term[idx]
                if msg.get("role") == "user":
                    text = msg.get("content") or ""
        if not text:
            return jsonify({"error": "No message text"}), 400
        return jsonify(agent.remember(layer, text))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/memory/delete")
def memory_delete():
    data = request.get_json(silent=True) or {}
    layer = (data.get("layer") or "").strip()
    key = (data.get("key") or "").strip()
    try:
        agent = get_agent()
        if not key:
            return jsonify({"error": "key is required"}), 400
        if layer == "working":
            agent.delete_working_item(key)
        elif layer == "long_term":
            agent.delete_long_term_item(key)
        else:
            return jsonify({"error": "layer must be working or long_term"}), 400
        return jsonify({"ok": True, "state": agent.snapshot()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/memory/clear")
def memory_clear():
    data = request.get_json(silent=True) or {}
    layer = (data.get("layer") or "all").strip()
    try:
        agent = get_agent()
        agent.clear_layer(layer)
        return jsonify({"ok": True, "state": agent.snapshot()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
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
    items = [
        {"id": m, "context_window": MODEL_CONTEXT_WINDOWS.get(m, 0)}
        for m in sorted(ALLOWED_MODELS)
    ]
    return jsonify({"models": items, "windows": dict(MODEL_CONTEXT_WINDOWS)})
