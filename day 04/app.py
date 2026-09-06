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

TEMPERATURES = [0.0, 0.7, 1.2]

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


def _parse_samples(raw):
    if raw is None or raw == "":
        return 2
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("samples must be an integer") from exc
    if value < 1 or value > 3:
        raise ValueError("samples must be between 1 and 3")
    return value


def _temp_key(temp):
    if temp == 0.0:
        return "0"
    return str(temp)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/temperature")
def temperature_compare():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "sk-your-key-here":
        return jsonify({"error": "Set OPENAI_API_KEY in day 04/.env"}), 400

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    model = (data.get("model") or "gpt-5.4").strip()

    if not prompt:
        return jsonify({"error": "Prompt is empty"}), 400
    if model not in ALLOWED_MODELS:
        return jsonify({"error": f"Model not allowed: {model}"}), 400

    try:
        samples = _parse_samples(data.get("samples"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    client = OpenAI(api_key=api_key)
    messages = [{"role": "user", "content": prompt}]
    temps = {}

    for temp in TEMPERATURES:
        key = _temp_key(temp)
        results = []
        for index in range(samples):
            try:
                results.append(
                    _run_completion(
                        client,
                        model=model,
                        messages=messages,
                        temperature=temp,
                    )
                )
            except Exception as exc:
                results.append({"error": f"sample {index + 1}: {exc}"})
        temps[key] = results

    return jsonify({"temps": temps})


if __name__ == "__main__":
    app.run(debug=True)
