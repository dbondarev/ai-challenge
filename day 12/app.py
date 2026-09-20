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
        _agent = Agent(api_key=api_key, base_dir=BASE_DIR)
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
    try:
        agent = get_agent()
        if data.get("role") is not None:
            agent.set_role(data.get("role") or "")
        model = (data.get("model") or "").strip()
        if model:
            agent.set_model(model)
        if data.get("window_size") not in (None, ""):
            agent.set_window_size(int(data["window_size"]))
        if data.get("profile_id"):
            agent.set_active_profile(
                str(data["profile_id"]),
                clear_dialog=bool(data.get("clear_dialog_on_switch", True)),
            )
        if not prompt:
            return jsonify({"error": "Empty prompt"}), 400
        return jsonify(agent.reply(prompt))
    except ContextOverflowError as exc:
        return jsonify({"error": str(exc), "tokens": exc.tokens}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/profiles")
def profiles_list():
    try:
        agent = get_agent()
        return jsonify(
            {
                "active_profile_id": agent.active_profile_id,
                "profiles": agent.list_profiles(),
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/profiles")
def profiles_upsert():
    data = request.get_json(silent=True) or {}
    try:
        agent = get_agent()
        text = (data.get("text") or data.get("description") or "").strip()
        if text and not data.get("name"):
            profile = agent.create_profile_from_text(
                text,
                activate=bool(data.get("activate", True)),
            )
            return jsonify({"ok": True, "profile": profile, "state": agent.snapshot()})

        profile = agent.upsert_profile(
            profile_id=(data.get("id") or data.get("profile_id") or None),
            name=str(data.get("name") or ""),
            preferences=data.get("preferences"),
            notes=str(data.get("notes") or ""),
        )
        if data.get("activate"):
            agent.set_active_profile(profile["id"])
        return jsonify({"ok": True, "profile": profile, "state": agent.snapshot()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/profiles/activate")
def profiles_activate():
    data = request.get_json(silent=True) or {}
    try:
        agent = get_agent()
        agent.set_active_profile(
            str(data.get("profile_id") or ""),
            clear_dialog=bool(data.get("clear_dialog", True)),
        )
        return jsonify({"ok": True, "state": agent.snapshot()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/profiles/delete")
def profiles_delete():
    data = request.get_json(silent=True) or {}
    try:
        agent = get_agent()
        agent.delete_profile(str(data.get("profile_id") or ""))
        return jsonify({"ok": True, "state": agent.snapshot()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
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


@app.get("/api/models")
def models():
    return jsonify({"models": sorted(ALLOWED_MODELS)})
