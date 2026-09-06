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

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/chat")
def chat():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "sk-your-key-here":
        return jsonify({"error": "Set OPENAI_API_KEY in day 01/.env"}), 400

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    model = (data.get("model") or "gpt-5.4").strip()

    if not prompt:
        return jsonify({"error": "Prompt is empty"}), 400
    if model not in ALLOWED_MODELS:
        return jsonify({"error": f"Model not allowed: {model}"}), 400

    try:
        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        reply = completion.choices[0].message.content or ""
        return jsonify({"reply": reply})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True)
