from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from agent import (
    ALLOWED_MODELS,
    Agent,
    ContextOverflowError,
    InvalidTransitionError,
)

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


@app.post("/api/task/create")
def task_create():
    data = request.get_json(silent=True) or {}
    try:
        agent = get_agent()
        model = (data.get("model") or "").strip()
        if model:
            agent.set_model(model)
        if data.get("role") is not None:
            agent.set_role(data.get("role") or "")
        return jsonify(agent.create_task(str(data.get("text") or data.get("brief") or "")))
    except ContextOverflowError as exc:
        return jsonify({"error": str(exc), "tokens": getattr(exc, "tokens", None)}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/task/select")
def task_select():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_agent().select_task(str(data.get("task_id") or "")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/task/delete")
def task_delete():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            {"ok": True, "state": get_agent().delete_task(str(data.get("task_id") or ""))}
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/task/approve-plan")
def task_approve_plan():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_agent().approve_plan(summary=data.get("summary")))
    except InvalidTransitionError as exc:
        snap = get_agent().snapshot()
        return jsonify({"error": str(exc), "task": snap.get("task"), "state": snap}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/task/advance")
def task_advance():
    try:
        return jsonify(get_agent().advance())
    except InvalidTransitionError as exc:
        snap = get_agent().snapshot()
        return jsonify({"error": str(exc), "task": snap.get("task"), "state": snap}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/task/transition")
def task_transition():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            get_agent().transition(
                str(data.get("stage") or ""),
                note=str(data.get("note") or ""),
            )
        )
    except InvalidTransitionError as exc:
        snap = get_agent().snapshot()
        return jsonify({"error": str(exc), "task": snap.get("task"), "state": snap}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/task/pause")
def task_pause():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_agent().pause(str(data.get("reason") or "")))
    except InvalidTransitionError as exc:
        snap = get_agent().snapshot()
        return jsonify({"error": str(exc), "task": snap.get("task"), "state": snap}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/task/resume")
def task_resume():
    try:
        return jsonify(get_agent().resume())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/task/comment")
def task_comment():
    data = request.get_json(silent=True) or {}
    try:
        agent = get_agent()
        model = (data.get("model") or "").strip()
        if model:
            agent.set_model(model)
        text = (data.get("text") or data.get("comment") or data.get("prompt") or "").strip()
        return jsonify(agent.comment(text))
    except ContextOverflowError as exc:
        return jsonify({"error": str(exc), "tokens": getattr(exc, "tokens", None)}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/chat")
def chat():
    return task_comment()


@app.post("/api/test/scripted")
def test_scripted():
    """Enable/disable deterministic replies for live UI auto-test."""
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_agent().set_scripted(bool(data.get("enabled"))))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/test/control")
def test_control():
    """Headless Day 15 control scenario (no UI typing). Prefer live Автотест in UI."""
    try:
        agent = get_agent()
        prev = agent.scripted
        agent.scripted = True
        try:
            return jsonify(agent.run_control_test())
        finally:
            agent.scripted = prev
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/task/fail-validation")
def task_fail_validation():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            get_agent().fail_validation(
                str(data.get("detail") or ""),
                fix_step=str(data.get("fix_step") or "fix_duplicate_subscription"),
            )
        )
    except InvalidTransitionError as exc:
        snap = get_agent().snapshot()
        return jsonify({"error": str(exc), "task": snap.get("task"), "state": snap}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/models")
def models():
    return jsonify({"models": sorted(ALLOWED_MODELS)})
