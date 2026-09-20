from __future__ import annotations

import json
import re
import uuid
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

# Same windows as day 08 — not user-editable
MODEL_CONTEXT_WINDOWS = {
    "gpt-5.4": 1_050_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.4-nano": 400_000,
    "gpt-5.5": 1_050_000,
    "gpt-4o": 128_000,
}

DEFAULT_WINDOW_SIZE = 20
MEMORY_LAYERS = ("short_term", "working", "long_term")


def model_context_window(model: str) -> int:
    return MODEL_CONTEXT_WINDOWS.get(model, 128_000)


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


def _clean_kv(items: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (items or {}).items():
        k = str(key).strip()
        if not k:
            continue
        out[k] = str(value).strip() if value is not None else ""
    return out


def _format_kv_block(title: str, items: dict[str, str]) -> Optional[str]:
    lines = [f"- {k}: {v}" for k, v in items.items() if v]
    if not lines:
        return None
    return f"{title}:\n" + "\n".join(lines)


def _parse_json_object(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
    except Exception:
        pass
    return {}


def _slug_key(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^\w.]+", "", text, flags=re.UNICODE)
    return (text or "fact")[:48]


class Agent:
    """Three memory layers: ephemeral dialog, working task, long-term profile."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4",
        role: str = "",
        base_dir: Optional[Path] = None,
    ):
        if not api_key or api_key == "sk-your-key-here":
            raise ValueError("OPENAI_API_KEY is missing or placeholder")
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model not allowed: {model}")

        self._client = OpenAI(api_key=api_key)
        self.base_dir = Path(base_dir) if base_dir else Path(".")
        self.settings_path = self.base_dir / "settings.json"
        self.working_path = self.base_dir / "working.json"
        self.long_term_path = self.base_dir / "long_term.json"

        default_role = (
            "\u0422\u044b \u043f\u043e\u043b\u0435\u0437\u043d\u044b\u0439 \u0430\u0441\u0441\u0438\u0441\u0442\u0435\u043d\u0442. "
            "\u0423\u0447\u0438\u0442\u044b\u0432\u0430\u0439 Working memory \u0438 Long-term memory, "
            "\u0435\u0441\u043b\u0438 \u043e\u043d\u0438 \u043f\u0435\u0440\u0435\u0434\u0430\u043d\u044b. "
            "\u041e\u0442\u0432\u0435\u0447\u0430\u0439 \u043a\u0440\u0430\u0442\u043a\u043e."
        )
        self.model = model
        self.role = (role or default_role).strip()
        self.window_size = DEFAULT_WINDOW_SIZE
        self.usage_log: list[dict] = []

        # Dialog is RAM-only — gone on process restart / explicit clear / page boot
        self.short_term: list[dict] = []
        self.working_title = ""
        self.working_task_id = ""
        self.working: dict[str, str] = {}
        self.long_term: dict[str, str] = {}

        self.last_api_messages: list[dict] = []
        self.last_tokens: dict[str, Any] = {}

        self._load_persistent()

    def _load_persistent(self) -> None:
        if self.settings_path.exists():
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if data.get("role"):
                    self.role = str(data["role"]).strip()
                if data.get("model") in ALLOWED_MODELS:
                    self.model = data["model"]
                if data.get("window_size") not in (None, ""):
                    self.window_size = max(1, int(data["window_size"]))
                self.usage_log = list(data.get("usage_log") or [])
            except Exception:
                pass

        if self.working_path.exists():
            try:
                data = json.loads(self.working_path.read_text(encoding="utf-8"))
                self.working_title = str(data.get("title") or "").strip()
                self.working_task_id = str(data.get("task_id") or "").strip()
                self.working = _clean_kv(data.get("items") or {})
            except Exception:
                pass

        if self.long_term_path.exists():
            try:
                data = json.loads(self.long_term_path.read_text(encoding="utf-8"))
                if "items" in data:
                    self.long_term = _clean_kv(data.get("items") or {})
                else:
                    self.long_term = _clean_kv(data)
            except Exception:
                pass

        # Migrate away from old short_term.json messages if present
        old = self.base_dir / "short_term.json"
        if old.exists():
            try:
                data = json.loads(old.read_text(encoding="utf-8"))
                if isinstance(data, dict) and not self.settings_path.exists():
                    if data.get("role"):
                        self.role = str(data["role"]).strip()
                    if data.get("model") in ALLOWED_MODELS:
                        self.model = data["model"]
                    self._save_settings()
            except Exception:
                pass

    @property
    def context_limit(self) -> int:
        return model_context_window(self.model)
    def _save_settings(self) -> None:
        payload = {
            "role": self.role,
            "model": self.model,
            "window_size": self.window_size,
            "usage_log": self.usage_log[-80:],
        }
        self.settings_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _save_working(self) -> None:
        payload = {
            "task_id": self.working_task_id,
            "title": self.working_title,
            "items": dict(self.working),
        }
        self.working_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _save_long_term(self) -> None:
        payload = {"items": dict(self.long_term)}
        self.long_term_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def set_role(self, role: str) -> None:
        self.role = (role or "").strip()
        self._save_settings()

    def set_model(self, model: str) -> None:
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model not allowed: {model}")
        self.model = model
        self._save_settings()

    def set_window_size(self, n: int) -> None:
        value = int(n)
        if value < 1:
            raise ValueError("window_size must be >= 1")
        self.window_size = value
        self._save_settings()

    def set_working_item(self, key: str, value: str) -> None:
        k = str(key).strip()
        if not k:
            raise ValueError("working key is required")
        self.working[k] = str(value).strip() if value is not None else ""
        if not self.working_task_id:
            self.working_task_id = str(uuid.uuid4())[:8]
        self._save_working()

    def delete_working_item(self, key: str) -> None:
        self.working.pop(str(key).strip(), None)
        self._save_working()

    def set_long_term_item(self, key: str, value: str) -> None:
        k = str(key).strip()
        if not k:
            raise ValueError("long_term key is required")
        self.long_term[k] = str(value).strip() if value is not None else ""
        self._save_long_term()

    def delete_long_term_item(self, key: str) -> None:
        self.long_term.pop(str(key).strip(), None)
        self._save_long_term()

    def clear_short_term(self) -> None:
        self.short_term = []
        self.last_api_messages = []
        self.last_tokens = {}

    def clear_working(self) -> None:
        self.working = {}
        self.working_title = ""
        self.working_task_id = ""
        self._save_working()

    def clear_long_term(self) -> None:
        self.long_term = {}
        self._save_long_term()

    def clear_layer(self, layer: str) -> None:
        layer = (layer or "").strip()
        if layer in ("short_term", "short", "dialog"):
            self.clear_short_term()
        elif layer in ("working", "task"):
            # «Новая задача»: wipe task facts + dialog; keep long-term
            self.clear_working()
            self.clear_short_term()
        elif layer == "long_term":
            self.clear_long_term()
        elif layer == "all":
            self.reset()
        else:
            raise ValueError(f"Unknown layer: {layer}")

    def reset(self) -> None:
        self.clear_short_term()
        self.clear_working()
        self.clear_long_term()

    def boot_session(self) -> None:
        """Page refresh: wipe dialog only; keep working + long-term files."""
        self.clear_short_term()

    def _kv_system(self, title: str, items: dict[str, str]) -> Optional[dict]:
        text = _format_kv_block(title, items)
        if not text:
            return None
        return {"role": "system", "content": text}

    def _dialog_window(self) -> list[dict]:
        return list(self.short_term[-self.window_size :])

    def _build_api_messages(self) -> list[dict]:
        out: list[dict] = []
        if self.role:
            out.append({"role": "system", "content": self.role})
        lt = self._kv_system("Long-term memory", self.long_term)
        if lt:
            out.append(lt)
        title = "Working memory (current task)"
        if self.working_title:
            title = f"Working memory (current task: {self.working_title})"
        wm = self._kv_system(title, self.working)
        if wm:
            out.append(wm)
        out.extend(self._dialog_window())
        return out

    def _layer_token_breakdown(self, model: str) -> dict[str, int]:
        role_msgs = [{"role": "system", "content": self.role}] if self.role else []
        lt = self._kv_system("Long-term memory", self.long_term)
        title = "Working memory (current task)"
        if self.working_title:
            title = f"Working memory (current task: {self.working_title})"
        wm = self._kv_system(title, self.working)
        dialog = self._dialog_window()
        return {
            "role": count_messages_tokens(role_msgs, model) if role_msgs else 0,
            "long_term": count_messages_tokens([lt], model) if lt else 0,
            "working": count_messages_tokens([wm], model) if wm else 0,
            "short_term": count_messages_tokens(dialog, model) if dialog else 0,
        }

    def _estimate_tokens(self, api_messages: list[dict]) -> dict:
        model = self.model
        prompt_estimate = count_messages_tokens(api_messages, model)
        return {
            "model": model,
            "context_limit": self.context_limit,
            "window_size": self.window_size,
            "prompt_estimate": prompt_estimate,
            "over_limit": prompt_estimate > self.context_limit,
            "layers": self._layer_token_breakdown(model),
            "short_term_messages": len(self.short_term),
            "short_term_in_prompt": len(self._dialog_window()),
            "working_count": len(self.working),
            "long_term_count": len(self.long_term),
            "cost_usd": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }

    def snapshot(self) -> dict:
        api = self._build_api_messages()
        tokens = self.last_tokens or self._estimate_tokens(api)
        working_list = [{"key": k, "value": v} for k, v in self.working.items()]
        long_list = [{"key": k, "value": v} for k, v in self.long_term.items()]
        return {
            "role": self.role,
            "model": self.model,
            "context_limit": self.context_limit,
            "window_size": self.window_size,
            "task_title": self.working_title,
            "task_id": self.working_task_id,
            "short_term": list(self.short_term),
            "working": working_list,
            "long_term": long_list,
            "tokens": tokens,
            "last_tokens": tokens.get("total_tokens") or tokens.get("prompt_estimate") or 0,
            "last_api_messages": list(self.last_api_messages or api),
            "usage_log": list(self.usage_log[-20:]),
        }

    def reply(self, user_message: str) -> dict:
        text = (user_message or "").strip()
        if not text:
            raise ValueError("Empty message")

        self.short_term.append({"role": "user", "content": text})
        api_messages = self._build_api_messages()
        tokens = self._estimate_tokens(api_messages)
        self.last_api_messages = api_messages
        self.last_tokens = tokens

        if tokens["over_limit"]:
            self.short_term.pop()
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
            self.short_term.pop()
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
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost,
            }
        )
        self._save_settings()
        self.short_term.append({"role": "assistant", "content": reply})
        snap = self.snapshot()
        snap["reply"] = reply
        return snap

    def _extract_facts(self, layer: str, text: str) -> dict:
        """LLM decides keys/values (and task title for working). User never picks keys."""
        layer = (layer or "").strip()
        if layer not in ("working", "long_term"):
            raise ValueError("layer must be working or long_term")
        text = (text or "").strip()
        if not text:
            raise ValueError("Empty text")

        if layer == "working":
            existing = json.dumps(self.working, ensure_ascii=False)
            title = self.working_title or ""
            prompt = (
                "\u0418\u0437\u0432\u043b\u0435\u043a\u0438 \u0444\u0430\u043a\u0442\u044b "
                "\u0434\u043b\u044f WORKING memory (\u0442\u0435\u043a\u0443\u0449\u0430\u044f \u0437\u0430\u0434\u0430\u0447\u0430) "
                "\u0438\u0437 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f.\n"
                "\u0412\u0435\u0440\u043d\u0438 \u0422\u041e\u041b\u042c\u041a\u041e JSON:\n"
                '{"task_title":"\u043a\u043e\u0440\u043e\u0442\u043a\u043e\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0437\u0430\u0434\u0430\u0447\u0438",'
                '"facts":[{"key":"snake_case_key","value":"..."}]}\n'
                "key \u043f\u0440\u0438\u0434\u0443\u043c\u044b\u0432\u0430\u0435\u0448\u044c \u0441\u0430\u043c (\u043a\u043e\u0440\u043e\u0442\u043a\u0438\u0439 snake_case). "
                "\u041e\u0431\u043d\u043e\u0432\u043b\u044f\u0439 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u044e\u0449\u0438\u0435 \u043a\u043b\u044e\u0447\u0438, \u0435\u0441\u043b\u0438 \u0444\u0430\u043a\u0442 \u0443\u0442\u043e\u0447\u043d\u0451\u043d.\n"
                f"\u0422\u0435\u043a\u0443\u0449\u0435\u0435 title: {title!r}\n"
                f"\u0423\u0436\u0435 working: {existing}\n\n"
                f"\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435:\n{text}"
            )
        else:
            existing = json.dumps(self.long_term, ensure_ascii=False)
            prompt = (
                "\u0418\u0437\u0432\u043b\u0435\u043a\u0438 \u0443\u0441\u0442\u043e\u0439\u0447\u0438\u0432\u044b\u0435 \u0444\u0430\u043a\u0442\u044b "
                "\u0434\u043b\u044f LONG-TERM memory (\u043f\u0440\u043e\u0444\u0438\u043b\u044c, \u043f\u0440\u0435\u0434\u043f\u043e\u0447\u0442\u0435\u043d\u0438\u044f, "
                "\u0440\u0435\u0448\u0435\u043d\u0438\u044f, \u0437\u043d\u0430\u043d\u0438\u044f) "
                "\u0438\u0437 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f.\n"
                "\u0412\u0435\u0440\u043d\u0438 \u0422\u041e\u041b\u042c\u041a\u041e JSON:\n"
                '{"facts":[{"key":"profile.name","value":"..."}]}\n'
                "\u041f\u0440\u0435\u0444\u0438\u043a\u0441\u044b \u043a\u043b\u044e\u0447\u0435\u0439: profile. / decision. / knowledge. "
                "\u041a\u043b\u044e\u0447\u0438 \u043f\u0440\u0438\u0434\u0443\u043c\u044b\u0432\u0430\u0435\u0448\u044c \u0441\u0430\u043c.\n"
                f"\u0423\u0436\u0435 long_term: {existing}\n\n"
                f"\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435:\n{text}"
            )

        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "\u0422\u044b \u0438\u0437\u0432\u043b\u0435\u043a\u0430\u0435\u0448\u044c "
                        "\u0444\u0430\u043a\u0442\u044b \u0434\u043b\u044f \u043f\u0430\u043c\u044f\u0442\u0438. "
                        "\u041e\u0442\u0432\u0435\u0447\u0430\u0439 \u0442\u043e\u043b\u044c\u043a\u043e JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = _parse_json_object(raw)
        facts_raw = parsed.get("facts") if isinstance(parsed, dict) else None
        facts: dict[str, str] = {}
        if isinstance(facts_raw, list):
            for item in facts_raw:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip() or _slug_key(
                    str(item.get("value") or "")
                )
                value = str(item.get("value") or "").strip()
                if key and value:
                    facts[key] = value
        elif isinstance(facts_raw, dict):
            facts = _clean_kv(facts_raw)

        if not facts:
            # Fallback: store whole message under agent-chosen key
            facts = {_slug_key(text[:32]): text}

        task_title = ""
        if layer == "working":
            task_title = str(parsed.get("task_title") or "").strip()

        usage = getattr(response, "usage", None)
        self.usage_log.append(
            {
                "kind": "remember",
                "layer": layer,
                "model": self.model,
                "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                "completion_tokens": getattr(usage, "completion_tokens", None)
                if usage
                else None,
            }
        )
        self._save_settings()
        return {"facts": facts, "task_title": task_title, "raw": raw}

    def remember(self, layer: str, text: str) -> dict:
        """Save user message into working or long_term; keys chosen by agent code/LLM."""
        extracted = self._extract_facts(layer, text)
        facts = extracted["facts"]
        if layer == "working":
            if not self.working_task_id:
                self.working_task_id = str(uuid.uuid4())[:8]
            self.working.update(facts)
            title = extracted.get("task_title") or ""
            if title:
                self.working_title = title
            elif not self.working_title:
                # derive short title from first fact
                first = next(iter(facts.values()), text)
                self.working_title = (first[:60] + "\u2026") if len(first) > 60 else first
            self._save_working()
        else:
            self.long_term.update(facts)
            self._save_long_term()

        snap = self.snapshot()
        added = [{"key": k, "value": v} for k, v in facts.items()]
        return {
            "ok": True,
            "layer": layer,
            "saved": facts,
            "added": added,
            "task_title": self.working_title if layer == "working" else None,
            "state": snap,
        }
