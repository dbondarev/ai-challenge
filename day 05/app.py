import os
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Approximate public list prices (USD per 1M tokens). Verify on OpenAI pricing page.
PRICING = {
    "gpt-5.4-nano": {"input_per_mtok": 0.20, "output_per_mtok": 1.25},
    "gpt-5.4-mini": {"input_per_mtok": 0.75, "output_per_mtok": 4.50},
    "gpt-5.5": {"input_per_mtok": 5.00, "output_per_mtok": 30.00},
}

TIERS = {
    "weak": "gpt-5.4-nano",
    "medium": "gpt-5.4-mini",
    "strong": "gpt-5.5",
}

# gpt-5.5 only accepts the default temperature (1); omit custom values.
FIXED_DEFAULT_TEMPERATURE_MODELS = {"gpt-5.5"}

app = Flask(__name__)


def _usage_dict(usage):
    if usage is None:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _estimate_cost_usd(model, usage):
    pricing = PRICING.get(model)
    if not pricing or not usage:
        return None
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0
    cost = (prompt / 1_000_000) * pricing["input_per_mtok"] + (
        completion / 1_000_000
    ) * pricing["output_per_mtok"]
    return round(cost, 8)


def _run_tier(client, *, model, prompt):
    pricing = PRICING[model]
    messages = [{"role": "user", "content": prompt}]
    kwargs = {
        "model": model,
        "messages": messages,
    }
    if model in FIXED_DEFAULT_TEMPERATURE_MODELS:
        used_temperature = 1
    else:
        used_temperature = 0
        kwargs["temperature"] = 0

    started = time.perf_counter()
    completion = client.chat.completions.create(**kwargs)
    latency_ms = int((time.perf_counter() - started) * 1000)
    choice = completion.choices[0]
    usage = _usage_dict(completion.usage)
    return {
        "model": model,
        "reply": choice.message.content or "",
        "finish_reason": choice.finish_reason,
        "latency_ms": latency_ms,
        "usage": usage,
        "cost_usd": _estimate_cost_usd(model, usage),
        "pricing": pricing,
        "temperature": used_temperature,
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/models")
def models_compare():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "sk-your-key-here":
        return jsonify({"error": "Set OPENAI_API_KEY in day 05/.env"}), 400

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is empty"}), 400

    client = OpenAI(api_key=api_key)
    results = {}
    for tier, model in TIERS.items():
        try:
            results[tier] = _run_tier(client, model=model, prompt=prompt)
        except Exception as exc:
            results[tier] = {"model": model, "error": str(exc)}

    return jsonify({"results": results})


if __name__ == "__main__":
    app.run(debug=True)
