from __future__ import annotations

import json
import uuid
from copy import deepcopy
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

PRICING = {
    "gpt-5.4": {"input_per_mtok": 2.50, "output_per_mtok": 15.00},
    "gpt-5.4-mini": {"input_per_mtok": 0.75, "output_per_mtok": 4.50},
    "gpt-5.4-nano": {"input_per_mtok": 0.20, "output_per_mtok": 1.25},
    "gpt-5.5": {"input_per_mtok": 5.00, "output_per_mtok": 30.00},
    "gpt-4o": {"input_per_mtok": 2.50, "output_per_mtok": 10.00},
}

DEFAULT_CONTEXT_LIMIT = 8192
DEFAULT_WINDOW_SIZE = 20

CATEGORIES = ("architecture", "tech_decision", "stack", "business_rule")


class ContextOverflowError(ValueError):
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
    return len(_encoding_for_model(model).encode(text or ""))


def count_messages_tokens(messages: list[dict], model: str) -> int:
    enc = _encoding_for_model(model)
    total = 0
    for message in messages:
        total += 4
        for value in message.values():
            total += len(enc.encode(str(value)))
    return total + 3


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = PRICING.get(model) or {"input_per_mtok": 0.0, "output_per_mtok": 0.0}
    return round(
        (prompt_tokens / 1_000_000) * pricing["input_per_mtok"]
        + (completion_tokens / 1_000_000) * pricing["output_per_mtok"],
        8,
    )


def _demo_invariants_ru() -> list[dict]:
    return [
        {
            "id": "arch-monolith",
            "category": "architecture",
            "statement": (
                "v1: \u043c\u043e\u043d\u043e\u043b\u0438\u0442\u043d\u044b\u0439 Flask API + "
                "\u043e\u0434\u0438\u043d SPA. \u041c\u0438\u043a\u0440\u043e\u0441\u0435\u0440\u0432\u0438\u0441\u044b "
                "/ \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u044b\u0435 deployable-\u0441\u0435\u0440\u0432\u0438\u0441\u044b "
                "\u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u044b."
            ),
            "active": True,
        },
        {
            "id": "auth-session",
            "category": "tech_decision",
            "statement": (
                "Auth \u0432 v1 \u0442\u043e\u043b\u044c\u043a\u043e session/cookie. "
                "JWT \u0432 v1 \u0437\u0430\u043f\u0440\u0435\u0449\u0451\u043d."
            ),
            "active": True,
        },
        {
            "id": "stack-frontend",
            "category": "stack",
            "statement": (
                "Frontend \u0442\u043e\u043b\u044c\u043a\u043e Vue 3 + TypeScript. "
                "React \u0438 Angular \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u044b."
            ),
            "active": True,
        },
        {
            "id": "stack-backend",
            "category": "stack",
            "statement": (
                "Backend: Python 3.11+ \u0438 Flask. "
                "Node/Django \u0432 v1 \u043d\u0435 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u043c."
            ),
            "active": True,
        },
        {
            "id": "biz-kyle-share",
            "category": "business_rule",
            "statement": (
                "\u041a\u0430\u0439\u043b \u043f\u043e\u043b\u0443\u0447\u0430\u0435\u0442 "
                "\u043c\u0430\u043a\u0441\u0438\u043c\u0443\u043c 20% \u043f\u0440\u0438\u0431\u044b\u043b\u0438. "
                "\u0411\u043e\u043b\u044c\u0448\u0435 \u2014 \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e."
            ),
            "active": True,
        },
        {
            "id": "biz-price-floor",
            "category": "business_rule",
            "statement": (
                "\u0426\u0435\u043d\u0430 \u043f\u0430\u0447\u043a\u0438 Cheesy Poofs "
                "\u043d\u0435 \u043d\u0438\u0436\u0435 $2."
            ),
            "active": True,
        },
    ]


def _normalize_item(raw: dict, *, fallback_id: Optional[str] = None) -> dict:
    category = str(raw.get("category") or "tech_decision").strip()
    if category not in CATEGORIES:
        category = "tech_decision"
    statement = str(raw.get("statement") or "").strip()
    item_id = str(raw.get("id") or fallback_id or uuid.uuid4().hex[:10]).strip()
    active = raw.get("active")
    if active is None:
        active = True
    return {
        "id": item_id,
        "category": category,
        "statement": statement,
        "active": bool(active),
    }


class InvariantsStore:
    """Invariants stored separately from dialog history."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.items: list[dict] = []
        self._load()
        if not self.items:
            self.reset_demo()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            raw_items = data.get("items") if isinstance(data, dict) else data
            cleaned = []
            for item in raw_items or []:
                if not isinstance(item, dict):
                    continue
                norm = _normalize_item(item)
                if norm["statement"]:
                    cleaned.append(norm)
            self.items = cleaned
        except Exception:
            pass

    def save(self) -> None:
        payload = {"items": self.items}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def list_all(self) -> list[dict]:
        return deepcopy(self.items)

    def list_active(self) -> list[dict]:
        return [deepcopy(i) for i in self.items if i.get("active")]

    def upsert(
        self,
        *,
        item_id: Optional[str] = None,
        category: str = "tech_decision",
        statement: str = "",
        active: bool = True,
    ) -> dict:
        statement = (statement or "").strip()
        if not statement:
            raise ValueError("statement is required")
        if category not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")

        if item_id:
            for i, item in enumerate(self.items):
                if item["id"] == item_id:
                    self.items[i] = _normalize_item(
                        {
                            "id": item_id,
                            "category": category,
                            "statement": statement,
                            "active": active,
                        }
                    )
                    self.save()
                    return deepcopy(self.items[i])

        new_id = item_id or f"inv-{uuid.uuid4().hex[:8]}"
        item = _normalize_item(
            {
                "id": new_id,
                "category": category,
                "statement": statement,
                "active": active,
            }
        )
        self.items.append(item)
        self.save()
        return deepcopy(item)

    def toggle(self, item_id: str, active: Optional[bool] = None) -> dict:
        for item in self.items:
            if item["id"] == item_id:
                item["active"] = (not item["active"]) if active is None else bool(active)
                self.save()
                return deepcopy(item)
        raise ValueError(f"Unknown invariant: {item_id}")

    def delete(self, item_id: str) -> None:
        before = len(self.items)
        self.items = [i for i in self.items if i["id"] != item_id]
        if len(self.items) == before:
            raise ValueError(f"Unknown invariant: {item_id}")
        self.save()

    def reset_demo(self) -> list[dict]:
        self.items = _demo_invariants_ru()
        self.save()
        return self.list_all()

    def to_system_message(self) -> Optional[dict]:
        active = self.list_active()
        if not active:
            return None
        lines = [
            "INVARIANTS (must not violate — authoritative, separate from dialog):",
        ]
        for item in active:
            lines.append(f"- [{item['category']}] ({item['id']}) {item['statement']}")
        lines.extend(
            [
                "Rules:",
                "1. Before proposing any solution, check it against EVERY active invariant.",
                "2. If the user request conflicts with an invariant — REFUSE.",
                "3. In a refusal: name the invariant id/category, quote the rule briefly, explain the conflict.",
                "4. Do not invent workarounds that break invariants.",
                "5. You may offer compliant alternatives that stay inside the invariants.",
                "6. In reasoning, explicitly mention which invariants you checked when relevant.",
            ]
        )
        return {"role": "system", "content": "\n".join(lines)}


class Agent:
    """Assistant that must respect separately stored invariants."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4",
        role: str = "",
        base_dir: Optional[Path] = None,
        context_limit: int = DEFAULT_CONTEXT_LIMIT,
    ):
        if not api_key or api_key == "sk-your-key-here":
            raise ValueError("OPENAI_API_KEY is missing or placeholder")
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model not allowed: {model}")

        self._client = OpenAI(api_key=api_key)
        self.base_dir = Path(base_dir) if base_dir else Path(".")
        self.history_path = self.base_dir / "history.json"
        self.invariants = InvariantsStore(self.base_dir / "invariants.json")

        default_role = (
            "\u0422\u044b \u0430\u0441\u0441\u0438\u0441\u0442\u0435\u043d\u0442, "
            "\u043a\u043e\u0442\u043e\u0440\u044b\u0439 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442 "
            "\u0441\u0442\u0440\u043e\u0433\u043e \u0432 \u0440\u0430\u043c\u043a\u0430\u0445 "
            "INVARIANTS. "
            "\u041f\u0440\u0438 \u043a\u043e\u043d\u0444\u043b\u0438\u043a\u0442\u0435 "
            "\u0441 \u0437\u0430\u043f\u0440\u043e\u0441\u043e\u043c \u2014 "
            "\u043e\u0442\u043a\u0430\u0437\u044b\u0432\u0430\u0439 "
            "\u0438 \u043e\u0431\u044a\u044f\u0441\u043d\u044f\u0439, "
            "\u043a\u0430\u043a\u043e\u0435 \u043f\u0440\u0430\u0432\u0438\u043b\u043e "
            "\u043d\u0430\u0440\u0443\u0448\u0435\u043d\u043e. "
            "\u041d\u0435 \u043e\u0431\u0445\u043e\u0434\u0438 "
            "\u0438\u043d\u0432\u0430\u0440\u0438\u0430\u043d\u0442\u044b."
        )
        self.model = model
        self.role = (role or default_role).strip()
        self.context_limit = int(context_limit)
        self.window_size = DEFAULT_WINDOW_SIZE
        self.messages: list[dict] = []
        self.usage_log: list[dict] = []
        self.last_api_messages: list[dict] = []
        self.last_tokens: dict[str, Any] = {}
        self._load_history()

    def _load_history(self) -> None:
        if not self.history_path.exists():
            return
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
            msgs = data.get("messages") if isinstance(data, dict) else data
            cleaned = []
            for item in msgs or []:
                if item.get("role") in ("user", "assistant") and isinstance(
                    item.get("content"), str
                ):
                    cleaned.append(
                        {"role": item["role"], "content": item["content"]}
                    )
            self.messages = cleaned
            if isinstance(data, dict):
                if data.get("role"):
                    self.role = str(data["role"]).strip()
                if data.get("model") in ALLOWED_MODELS:
                    self.model = data["model"]
                if data.get("context_limit") not in (None, ""):
                    self.context_limit = int(data["context_limit"])
                if data.get("window_size") not in (None, ""):
                    self.window_size = max(1, int(data["window_size"]))
                self.usage_log = list(data.get("usage_log") or [])
        except Exception:
            pass

    def _save_history(self) -> None:
        payload = {
            "messages": self.messages,
            "role": self.role,
            "model": self.model,
            "context_limit": self.context_limit,
            "window_size": self.window_size,
            "usage_log": self.usage_log[-80:],
        }
        self.history_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def set_role(self, role: str) -> None:
        self.role = (role or "").strip()
        self._save_history()

    def set_model(self, model: str) -> None:
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model not allowed: {model}")
        self.model = model
        self._save_history()

    def set_context_limit(self, n: int) -> None:
        value = int(n)
        if value < 64:
            raise ValueError("context_limit must be >= 64")
        self.context_limit = value
        self._save_history()

    def set_window_size(self, n: int) -> None:
        value = int(n)
        if value < 1:
            raise ValueError("window_size must be >= 1")
        self.window_size = value
        self._save_history()

    def clear_dialog(self) -> None:
        self.messages = []
        self.last_api_messages = []
        self.last_tokens = {}
        self._save_history()

    def reset(self) -> None:
        """Clear dialog only; invariants stay (use reset_demo separately)."""
        self.clear_dialog()

    def _build_api_messages(self) -> list[dict]:
        out: list[dict] = []
        if self.role:
            out.append({"role": "system", "content": self.role})
        inv = self.invariants.to_system_message()
        if inv:
            out.append(inv)
        out.extend(self.messages[-self.window_size :])
        return out

    def _estimate_tokens(self, api_messages: list[dict]) -> dict:
        model = self.model
        prompt_estimate = count_messages_tokens(api_messages, model)
        role_msgs = [{"role": "system", "content": self.role}] if self.role else []
        inv = self.invariants.to_system_message()
        dialog = self.messages[-self.window_size :]
        return {
            "model": model,
            "context_limit": self.context_limit,
            "window_size": self.window_size,
            "prompt_estimate": prompt_estimate,
            "over_limit": prompt_estimate > self.context_limit,
            "layers": {
                "role": count_messages_tokens(role_msgs, model) if role_msgs else 0,
                "invariants": count_messages_tokens([inv], model) if inv else 0,
                "dialog": count_messages_tokens(dialog, model) if dialog else 0,
            },
            "active_invariants": len(self.invariants.list_active()),
            "cost_usd": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }

    def snapshot(self) -> dict:
        api = self._build_api_messages()
        tokens = self.last_tokens or self._estimate_tokens(api)
        return {
            "role": self.role,
            "model": self.model,
            "context_limit": self.context_limit,
            "window_size": self.window_size,
            "messages": list(self.messages),
            "invariants": self.invariants.list_all(),
            "categories": list(CATEGORIES),
            "tokens": tokens,
            "last_api_messages": list(self.last_api_messages or api),
            "usage_log": list(self.usage_log[-20:]),
        }

    def reply(self, user_message: str) -> dict:
        text = (user_message or "").strip()
        if not text:
            raise ValueError("Empty message")

        self.messages.append({"role": "user", "content": text})
        api_messages = self._build_api_messages()
        tokens = self._estimate_tokens(api_messages)
        self.last_api_messages = api_messages
        self.last_tokens = tokens

        if tokens["over_limit"]:
            self.messages.pop()
            self._save_history()
            raise ContextOverflowError(
                "context overflow: prompt_estimate exceeds context_limit",
                tokens,
            )

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=api_messages,
            )
        except Exception:
            self.messages.pop()
            self._save_history()
            raise

        reply = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = (
            getattr(usage, "completion_tokens", None) if usage else None
        )
        total_tokens = getattr(usage, "total_tokens", None) if usage else None
        cost = None
        if prompt_tokens is not None and completion_tokens is not None:
            cost = estimate_cost_usd(self.model, prompt_tokens, completion_tokens)

        tokens.update(
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost,
                "reply_estimate": count_text_tokens(reply, self.model),
            }
        )
        self.last_tokens = tokens
        self.usage_log.append(
            {
                "kind": "chat",
                "model": self.model,
                "active_invariants": tokens.get("active_invariants"),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost,
            }
        )
        self.messages.append({"role": "assistant", "content": reply})
        self._save_history()
        snap = self.snapshot()
        snap["reply"] = reply
        return snap
