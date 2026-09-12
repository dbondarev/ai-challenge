from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from openai import OpenAI

ALLOWED_MODELS = {
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.5",
    "gpt-4o",
}


class Agent:
    """LLM agent with persistent dialog history in a JSON file."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4",
        role: str = "",
        history_path: Optional[Path] = None,
    ):
        if not api_key or api_key == "sk-your-key-here":
            raise ValueError("OPENAI_API_KEY is missing or placeholder")
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model not allowed: {model}")

        self._client = OpenAI(api_key=api_key)
        self.history_path = Path(history_path) if history_path else Path("history.json")
        self.model = model
        self.role = (role or "").strip()
        self.messages: list[dict] = []
        self._load()

    def snapshot(self) -> dict:
        return {
            "model": self.model,
            "role": self.role,
            "messages": list(self.messages),
        }

    def set_model(self, model: str) -> None:
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model not allowed: {model}")
        self.model = model
        self._save()

    def set_role(self, role: str) -> None:
        self.role = (role or "").strip()
        self._save()

    def reset(self) -> None:
        self.messages = []
        self._save()

    def reply(self, user_message: str) -> dict:
        text = (user_message or "").strip()
        if not text:
            raise ValueError("User message is empty")

        self.messages.append({"role": "user", "content": text})

        api_messages = []
        if self.role:
            api_messages.append({"role": "system", "content": self.role})
        api_messages.extend(self.messages)

        try:
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=api_messages,
            )
        except Exception:
            self.messages.pop()
            raise

        choice = completion.choices[0]
        assistant_text = choice.message.content or ""
        self.messages.append({"role": "assistant", "content": assistant_text})
        self._save()

        usage = completion.usage
        return {
            "reply": assistant_text,
            "model": self.model,
            "role": self.role,
            "finish_reason": choice.finish_reason,
            "messages": list(self.messages),
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                "completion_tokens": getattr(usage, "completion_tokens", None)
                if usage
                else None,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
            },
        }

    def _load(self) -> None:
        if not self.history_path.exists():
            return
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        model = (data.get("model") or self.model).strip()
        if model in ALLOWED_MODELS:
            self.model = model
        self.role = (data.get("role") or self.role or "").strip()

        loaded = []
        for item in data.get("messages") or []:
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and isinstance(content, str):
                loaded.append({"role": role, "content": content})
        self.messages = loaded

    def _save(self) -> None:
        payload = {
            "model": self.model,
            "role": self.role,
            "messages": self.messages,
        }
        self.history_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
