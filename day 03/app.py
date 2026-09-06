import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

ALLOWED_MODELS = {
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.5",
    "gpt-4o",
}

DEFAULT_EXPERTS = ["аналитик", "инженер", "критик"]

app = Flask(__name__)


def _usage_dict(usage):
    if usage is None:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _run_completion(client, *, model, messages, **kwargs):
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        **kwargs,
    )
    choice = completion.choices[0]
    return {
        "reply": choice.message.content or "",
        "finish_reason": choice.finish_reason,
        "usage": _usage_dict(completion.usage),
    }


def _parse_temperature(raw):
    if raw is None or raw == "":
        return 0.3
    try:
        temp = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("temperature must be a number") from exc
    if not 0 <= temp <= 2:
        raise ValueError("temperature must be between 0 and 2")
    return temp


def _parse_experts(raw):
    if raw is None or not str(raw).strip():
        return list(DEFAULT_EXPERTS)
    experts = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not experts:
        return list(DEFAULT_EXPERTS)
    return experts


def _mode_direct(client, *, model, task, temperature):
    return _run_completion(
        client,
        model=model,
        messages=[{"role": "user", "content": task}],
        temperature=temperature,
    )


def _mode_step_by_step(client, *, model, task, temperature):
    return _run_completion(
        client,
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Решай пошагово. Покажи рассуждение, затем итоговый ответ."
                ),
            },
            {"role": "user", "content": task},
        ],
        temperature=temperature,
    )


def _mode_meta_prompt(client, *, model, task, temperature):
    step1 = _run_completion(
        client,
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты составляешь промпты для решения задач. "
                    "Верни только один готовый промпт на русском, без пояснений "
                    "и без markdown-обёрток. В промпт полностью включи формулировку задачи."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Составь один готовый промпт для решения следующей задачи.\n\n"
                    f"Задача:\n{task}"
                ),
            },
        ],
        temperature=temperature,
    )
    generated = (step1.get("reply") or "").strip()
    if not generated:
        return {
            "error": "Empty generated prompt from step 1",
            "generated_prompt": "",
            "step1_usage": step1.get("usage") or {},
        }

    step2 = _run_completion(
        client,
        model=model,
        messages=[{"role": "user", "content": generated}],
        temperature=temperature,
    )
    return {
        "generated_prompt": generated,
        "reply": step2.get("reply") or "",
        "finish_reason": step2.get("finish_reason"),
        "usage": step2.get("usage") or {},
        "step1_usage": step1.get("usage") or {},
    }


def _mode_experts(client, *, model, task, temperature, experts):
    roles = ", ".join(experts)
    role_lines = "\n".join(f"- {name}" for name in experts)
    system = (
        "Ты организуешь обсуждение группы экспертов.\n"
        f"Эксперты: {roles}.\n"
        "Для каждого эксперта дай отдельное решение под заголовком с его ролью.\n"
        "В конце добавь краткий общий итог.\n"
        f"Роли:\n{role_lines}"
    )
    return _run_completion(
        client,
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ],
        temperature=temperature,
    )


def _safe_mode(label, fn):
    try:
        return fn()
    except Exception as exc:
        return {"error": f"{label}: {exc}"}


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/reason")
def reason():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "sk-your-key-here":
        return jsonify({"error": "Set OPENAI_API_KEY in day 03/.env"}), 400

    data = request.get_json(silent=True) or {}
    task = (data.get("task") or "").strip()
    model = (data.get("model") or "gpt-5.4").strip()

    if not task:
        return jsonify({"error": "Task is empty"}), 400
    if model not in ALLOWED_MODELS:
        return jsonify({"error": f"Model not allowed: {model}"}), 400

    try:
        temperature = _parse_temperature(data.get("temperature"))
        experts = _parse_experts(data.get("experts"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    client = OpenAI(api_key=api_key)

    result = {
        "direct": _safe_mode(
            "direct",
            lambda: _mode_direct(
                client, model=model, task=task, temperature=temperature
            ),
        ),
        "step_by_step": _safe_mode(
            "step_by_step",
            lambda: _mode_step_by_step(
                client, model=model, task=task, temperature=temperature
            ),
        ),
        "meta_prompt": _safe_mode(
            "meta_prompt",
            lambda: _mode_meta_prompt(
                client, model=model, task=task, temperature=temperature
            ),
        ),
        "experts": _safe_mode(
            "experts",
            lambda: _mode_experts(
                client,
                model=model,
                task=task,
                temperature=temperature,
                experts=experts,
            ),
        ),
    }
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True)
