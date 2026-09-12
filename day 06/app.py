import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from agent import ALLOWED_MODELS, Agent

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/chat")
def chat():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    model = (data.get("model") or "gpt-5.4").strip()
    role = (data.get("role") or "").strip()

    if not prompt:
        return jsonify({"error": "Prompt is empty"}), 400
    if model not in ALLOWED_MODELS:
        return jsonify({"error": f"Model not allowed: {model}"}), 400

    try:
        agent = Agent(api_key=api_key, model=model, role=role)
        result = agent.reply(prompt)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True)
