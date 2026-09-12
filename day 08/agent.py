from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import tiktoken
from openai import OpenAI

ALLOWED_MODELS = {
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.5",
    "gpt-4o",
}

# Approximate USD per 1M tokens (public list prices).
PRICING = {
    "gpt-5.4": {"input_per_mtok": 2.50, "output_per_mtok": 15.00},
    "gpt-5.4-mini": {"input_per_mtok": 0.75, "output_per_mtok": 4.50},
    "gpt-5.4-nano": {"input_per_mtok": 0.20, "output_per_mtok": 1.25},
    "gpt-5.5": {"input_per_mtok": 5.00, "output_per_mtok": 30.00},
    "gpt-4o": {"input_per_mtok": 2.50, "output_per_mtok": 10.00},
}

# Official API context windows (input + output budget).
MODEL_CONTEXT_WINDOWS = {
    "gpt-5.4": 1_050_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.4-nano": 400_000,
    "gpt-5.5": 1_050_000,
    "gpt-4o": 128_000,
}


def model_context_window(model: str) -> int:
    return MODEL_CONTEXT_WINDOWS.get(model, 0)


class ContextOverflowError(ValueError):
    """Raised when estimated prompt tokens exceed the model's context window."""

    def __init__(self, message: str, tokens: dict):
        super().__init__(message)
        self.tokens = tokens


def _encoding_for_model(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        try:
            return tiktoken.get_encoding("o200k_base")
        except Exception:
            return tiktoken.get_encoding("cl100k_base")


def count_text_tokens(text: str, model: str) -> int:
    enc = _encoding_for_model(model)
    return len(enc.encode(text or ""))


def count_messages_tokens(messages: list[dict], model: str) -> int:
    """Approximate chat-messages token count (role overhead + content)."""
    enc = _encoding_for_model(model)
    tokens_per_message = 4
    total = 0
    for message in messages:
        total += tokens_per_message
        for value in message.values():
            total += len(enc.encode(str(value)))
    total += 3  # reply primer
    return total


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = PRICING.get(model) or {"input_per_mtok": 0.0, "output_per_mtok": 0.0}
    cost = (prompt_tokens / 1_000_000) * pricing["input_per_mtok"] + (
        completion_tokens / 1_000_000
    ) * pricing["output_per_mtok"]
    return round(cost, 8)


class Agent:
    """LLM agent with persistent history and token accounting."""

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
        self.usage_log: list[dict] = []
        self._load()

    @property
    def context_window(self) -> int:
        return model_context_window(self.model)

    def _api_messages(self, messages: Optional[list[dict]] = None) -> list[dict]:
        msgs = messages if messages is not None else self.messages
        api_messages: list[dict] = []
        if self.role:
            api_messages.append({"role": "system", "content": self.role})
        api_messages.extend(msgs)
        return api_messages

    def _token_fields(
        self,
        *,
        prompt_estimate: int,
        request_estimate: int = 0,
        history_estimate: Optional[int] = None,
        reply_estimate: int = 0,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        cost_usd=None,
        over_limit: Optional[bool] = None,
        **extra,
    ) -> dict:
        window = self.context_window
        hist = history_estimate if history_estimate is not None else prompt_estimate
        fields = {
            "history_estimate": hist,
            "prompt_estimate": prompt_estimate,
            "request_estimate": request_estimate,
            "reply_estimate": reply_estimate,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "model_context_window": window,
            "remaining_estimate": max(0, window - prompt_estimate),
            "context_used_pct": (
                round(100.0 * prompt_estimate / window, 2) if window > 0 else 0.0
            ),
            "over_limit": (
                over_limit
                if over_limit is not None
                else prompt_estimate > window
            ),
        }
        fields.update(extra)
        return fields

    def current_token_summary(self) -> dict:
        history_estimate = count_messages_tokens(self._api_messages(), self.model)
        return self._token_fields(
            prompt_estimate=history_estimate,
            history_estimate=history_estimate,
        )

    def snapshot(self) -> dict:
        return {
            "model": self.model,
            "role": self.role,
            "messages": list(self.messages),
            "model_context_window": self.context_window,
            "usage_log": list(self.usage_log),
            "tokens": self.current_token_summary(),
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
        self.usage_log = []
        self._save()

    def estimate_next_turn(
        self,
        user_message: str = "",
        model: Optional[str] = None,
        role: Optional[str] = None,
    ) -> dict:
        """Estimate tokens if this draft were sent now (does not mutate history)."""
        use_model = model or self.model
        if use_model not in ALLOWED_MODELS:
            raise ValueError(f"Model not allowed: {use_model}")
        use_role = self.role if role is None else (role or "").strip()

        text = user_message or ""
        request_estimate = count_text_tokens(text, use_model) if text.strip() else 0

        api_history: list[dict] = []
        if use_role:
            api_history.append({"role": "system", "content": use_role})
        api_history.extend(self.messages)
        history_estimate = count_messages_tokens(api_history, use_model)

        if text.strip():
            projected = list(api_history) + [
                {"role": "user", "content": text.strip()}
            ]
            prompt_estimate = count_messages_tokens(projected, use_model)
        else:
            prompt_estimate = history_estimate

        window = model_context_window(use_model)
        used_pct = (
            round(100.0 * prompt_estimate / window, 2) if window > 0 else 0.0
        )
        return {
            "model": use_model,
            "request_estimate": request_estimate,
            "history_estimate": history_estimate,
            "prompt_estimate": prompt_estimate,
            "model_context_window": window,
            "remaining_estimate": max(0, window - prompt_estimate),
            "context_used_pct": used_pct,
            "over_limit": prompt_estimate > window,
        }

    def reply(self, user_message: str) -> dict:
        text = (user_message or "").strip()
        if not text:
            raise ValueError("User message is empty")

        request_estimate = count_text_tokens(text, self.model)
        history_before = count_messages_tokens(self._api_messages(), self.model)

        self.messages.append({"role": "user", "content": text})
        api_messages = self._api_messages()
        prompt_estimate = count_messages_tokens(api_messages, self.model)
        history_estimate = count_messages_tokens(
            self._api_messages(self.messages[:-1]), self.model
        )
        window = self.context_window

        tokens_pre = self._token_fields(
            request_estimate=request_estimate,
            history_estimate=history_estimate,
            prompt_estimate=prompt_estimate,
            history_before_estimate=history_before,
        )

        if prompt_estimate > window:
            self.messages.pop()
            raise ContextOverflowError(
                (
                    f"context overflow: prompt_estimate={prompt_estimate} "
                    f"> model_context_window={window} ({self.model})"
                ),
                tokens_pre,
            )

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

        usage = completion.usage
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
        total_tokens = getattr(usage, "total_tokens", None) if usage else None
        reply_estimate = count_text_tokens(assistant_text, self.model)
        cost = estimate_cost_usd(
            self.model,
            int(prompt_tokens or prompt_estimate),
            int(completion_tokens or reply_estimate),
        )

        tokens = self._token_fields(
            request_estimate=request_estimate,
            history_estimate=count_messages_tokens(self._api_messages(), self.model),
            prompt_estimate=prompt_estimate,
            reply_estimate=reply_estimate,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            over_limit=False,
        )

        self.usage_log.append(
            {
                "turn": len(self.usage_log) + 1,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "prompt_estimate": prompt_estimate,
                "request_estimate": request_estimate,
                "reply_estimate": reply_estimate,
                "model_context_window": window,
                "cost_usd": cost,
            }
        )
        self._save()

        return {
            "reply": assistant_text,
            "model": self.model,
            "role": self.role,
            "finish_reason": choice.finish_reason,
            "messages": list(self.messages),
            "tokens": tokens,
            "usage_log": list(self.usage_log),
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
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

        log: list[dict[str, Any]] = []
        for item in data.get("usage_log") or []:
            if isinstance(item, dict):
                log.append(item)
        self.usage_log = log

    def _save(self) -> None:
        payload = {
            "model": self.model,
            "role": self.role,
            "messages": self.messages,
            "usage_log": self.usage_log,
        }
        self.history_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
