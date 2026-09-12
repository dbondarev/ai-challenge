from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from agent import ALLOWED_MODELS, Agent, ContextOverflowError

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)

_agent: Optional[Agent] = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        _agent = Agent(
            api_key=api_key,
            history_path=BASE_DIR / "history.json",
        )
    return _agent


@app.get("/")
def index():
    return render_template("index.html")


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

    if not prompt:
        return jsonify({"error": "Prompt is empty"}), 400
    if model and model not in ALLOWED_MODELS:
        return jsonify({"error": f"Model not allowed: {model}"}), 400

    try:
        agent = get_agent()
        if model:
            agent.set_model(model)
        if role is not None:
            agent.set_role(role)
        if context_limit is not None and context_limit != "":
            agent.set_context_limit(int(context_limit))
        if data.get("keep_last") not in (None, ""):
            agent.set_keep_last(int(data.get("keep_last")))
        if data.get("summarize_every") not in (None, ""):
            agent.set_summarize_every(int(data.get("summarize_every")))
        return jsonify(agent.reply(prompt))
    except ContextOverflowError as exc:
        return jsonify({"error": str(exc), "tokens": exc.tokens}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/compress")
def compress():
    try:
        return jsonify(get_agent().compress_now())
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


if __name__ == "__main__":
    app.run(debug=True)
