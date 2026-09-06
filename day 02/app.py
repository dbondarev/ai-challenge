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

# GPT-5.x Chat Completions reject the `stop` parameter.
STOP_SUPPORTED_MODELS = {"gpt-4o"}

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


def _build_system(controls):
    parts = []
    fmt = (controls.get("format") or "").strip()
    if fmt:
        parts.append(fmt)

    if controls.get("soft_length"):
        parts.append("Ответь не длиннее 3 предложений.")

    if controls.get("soft_stop"):
        parts.append('Заверши ответ словом END (после последнего предложения).')

    response_format = (controls.get("response_format") or "text").strip()
    if response_format == "json_object":
        parts.append("Ответь только валидным JSON-объектом, без markdown и пояснений.")

    return "\n\n".join(parts)


def _build_api_kwargs(controls, model):
    api = {}
    echo = {}

    max_tokens = controls.get("max_completion_tokens")
    if max_tokens is not None and max_tokens != "":
        try:
            value = int(max_tokens)
        except (TypeError, ValueError):
            raise ValueError("max_completion_tokens must be an integer") from None
        if value < 1:
            raise ValueError("max_completion_tokens must be >= 1")
        api["max_completion_tokens"] = value
        echo["max_completion_tokens"] = value

    stop_raw = (controls.get("stop") or "").strip()
    if stop_raw:
        stops = [s.strip() for s in stop_raw.split("|") if s.strip()][:4]
        if stops:
            if model in STOP_SUPPORTED_MODELS:
                api["stop"] = stops
                echo["stop"] = stops
            else:
                echo["stop_skipped"] = (
                    f"stop={stops!r} not sent: unsupported for model {model}. "
                    "Use soft stop in system, or switch to gpt-4o."
                )

    response_format = (controls.get("response_format") or "text").strip()
    if response_format == "json_object":
        api["response_format"] = {"type": "json_object"}
        echo["response_format"] = {"type": "json_object"}
    elif response_format != "text":
        raise ValueError("response_format must be text or json_object")

    temperature = controls.get("temperature")
    if temperature is not None and temperature != "":
        try:
            temp = float(temperature)
        except (TypeError, ValueError):
            raise ValueError("temperature must be a number") from None
        if not 0 <= temp <= 2:
            raise ValueError("temperature must be between 0 and 2")
        api["temperature"] = temp
        echo["temperature"] = temp

    return api, echo


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/compare")
def compare():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "sk-your-key-here":
        return jsonify({"error": "Set OPENAI_API_KEY in day 02/.env"}), 400

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    model = (data.get("model") or "gpt-5.4").strip()
    controls = data.get("controls") or {}

    if not prompt:
        return jsonify({"error": "Prompt is empty"}), 400
    if model not in ALLOWED_MODELS:
        return jsonify({"error": f"Model not allowed: {model}"}), 400

    try:
        api_kwargs, api_echo = _build_api_kwargs(controls, model)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    system = _build_system(controls)
    controlled_messages = []
    if system:
        controlled_messages.append({"role": "system", "content": system})
    controlled_messages.append({"role": "user", "content": prompt})

    try:
        client = OpenAI(api_key=api_key)
        unconstrained = _run_completion(
            client,
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        controlled = _run_completion(
            client,
            model=model,
            messages=controlled_messages,
            **api_kwargs,
        )
        controlled["request_echo"] = {
            "system": system,
            "api": api_echo,
        }
        return jsonify(
            {
                "unconstrained": unconstrained,
                "controlled": controlled,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True)
