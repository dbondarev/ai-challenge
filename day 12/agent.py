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

MODEL_CONTEXT_WINDOWS = {
    "gpt-5.4": 1_050_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.4-nano": 400_000,
    "gpt-5.5": 1_050_000,
    "gpt-4o": 128_000,
}

DEFAULT_WINDOW_SIZE = 20
PREF_KEYS = ("style", "format", "constraints", "language", "length", "emoji")


class ContextOverflowError(ValueError):
    def __init__(self, message: str, tokens: dict):
        super().__init__(message)
        self.tokens = tokens


def model_context_window(model: str) -> int:
    return MODEL_CONTEXT_WINDOWS.get(model, 128_000)


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


def _parse_json_object(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _extract_explicit_name(text: str) -> str:
    """If the user wrote Name: / Имя: — use that value as profile title, unchanged."""
    patterns = (
        r"(?im)^\s*name\s*[:：\-–]\s*(.+?)\s*$",
        r"(?im)^\s*profile\s*name\s*[:：\-–]\s*(.+?)\s*$",
        r"(?im)^\s*имя(?:\s+профиля)?\s*[:：\-–]\s*(.+?)\s*$",
        r"(?im)^\s*меня зовут\s+([^.\n!?]+)",
        r"(?im)^\s*my name is\s+([^.\n!?]+)",
    )
    for pat in patterns:
        m = re.search(pat, text or "")
        if m:
            name = m.group(1).strip().strip("\"'`")
            # drop trailing labels if line was "Kyle Style: ..."
            name = re.split(r"\s{2,}|\t", name)[0].strip()
            if name and len(name) <= 80:
                return name
    return ""


def _new_profile(
    name: str,
    *,
    preferences: Optional[dict] = None,
    notes: str = "",
    profile_id: Optional[str] = None,
) -> dict:
    prefs = {k: "" for k in PREF_KEYS}
    prefs.update(_clean_kv(preferences or {}))
    for k, v in _clean_kv(preferences or {}).items():
        prefs[k] = v
    return {
        "id": profile_id or str(uuid.uuid4())[:8],
        "name": (name or "User").strip(),
        "notes": (notes or "").strip(),
        "preferences": prefs,
    }


def _default_profiles() -> tuple[dict[str, dict], str]:
    cartman = _new_profile(
        "Эрик Картман",
        preferences={
            "style": "саркастичный, дерзкий, коротко, как у Картмана",
            "format": "короткие абзацы или 3–5 буллетов",
            "constraints": "не морализируй; не сюсюкай; можно лёгкий мат-намёк без жёсткости",
            "language": "ru",
            "length": "кратко",
            "emoji": "нет",
        },
        notes="Школьный бизнес Cheesy Poofs / Cartman Snacks",
        profile_id="cartman",
    )
    executive = _new_profile(
        "Анна (B2B)",
        preferences={
            "style": "спокойный, деловой, без hype",
            "format": "структура: вывод → пункты → следующий шаг",
            "constraints": "без эмодзи; без сленга; факты и цифры; язык English для названий OK",
            "language": "ru",
            "length": "средне",
            "emoji": "нет",
        },
        notes="Владелец малого B2B SaaS, собирает ТЗ на лендинг",
        profile_id="anna",
    )
    return {cartman["id"]: cartman, executive["id"]: executive}, cartman["id"]


class Agent:
    """Profile personalization + dialog. No working / long-term memory layers."""

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
        self.profiles_path = self.base_dir / "profiles.json"
        self.settings_path = self.base_dir / "settings.json"

        self.model = model
        default_role = (
            "Ты персональный ассистент. Всегда учитывай активный профиль пользователя "
            "(стиль, формат, ограничения). Не выдумывай факты о пользователе сверх профиля."
        )
        self.role = (role or default_role).strip()
        self.window_size = DEFAULT_WINDOW_SIZE
        self.usage_log: list[dict] = []

        self.profiles: dict[str, dict] = {}
        self.active_profile_id: str = ""
        self.messages: list[dict] = []

        self.last_api_messages: list[dict] = []
        self.last_tokens: dict[str, Any] = {}

        self._load()
        if not self.profiles:
            self.profiles, self.active_profile_id = _default_profiles()
            self._save_profiles()

    @property
    def context_limit(self) -> int:
        return model_context_window(self.model)

    def _load(self) -> None:
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
        # migrate old short_term.json settings if needed
        old = self.base_dir / "short_term.json"
        if old.exists() and not self.settings_path.exists():
            try:
                data = json.loads(old.read_text(encoding="utf-8"))
                if data.get("role"):
                    self.role = str(data["role"]).strip()
                if data.get("model") in ALLOWED_MODELS:
                    self.model = data["model"]
                self.usage_log = list(data.get("usage_log") or [])
                self._save_settings()
            except Exception:
                pass

        if self.profiles_path.exists():
            try:
                data = json.loads(self.profiles_path.read_text(encoding="utf-8"))
                raw = data.get("profiles") or {}
                cleaned: dict[str, dict] = {}
                for pid, p in raw.items():
                    if not isinstance(p, dict):
                        continue
                    cleaned[pid] = _new_profile(
                        p.get("name") or pid,
                        preferences=p.get("preferences"),
                        notes=p.get("notes") or "",
                        profile_id=pid,
                    )
                if cleaned:
                    self.profiles = cleaned
                    active = str(data.get("active_profile_id") or "")
                    self.active_profile_id = (
                        active if active in cleaned else next(iter(cleaned))
                    )
            except Exception:
                pass

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

    def _save_profiles(self) -> None:
        payload = {
            "active_profile_id": self.active_profile_id,
            "profiles": self.profiles,
        }
        self.profiles_path.write_text(
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

    def get_active_profile(self) -> Optional[dict]:
        return self.profiles.get(self.active_profile_id)

    def list_profiles(self) -> list[dict]:
        return [dict(p) for p in self.profiles.values()]

    def set_active_profile(self, profile_id: str, *, clear_dialog: bool = True) -> None:
        pid = (profile_id or "").strip()
        if pid not in self.profiles:
            raise ValueError(f"Unknown profile: {pid}")
        self.active_profile_id = pid
        self._save_profiles()
        if clear_dialog:
            self.clear_dialog()

    def upsert_profile(
        self,
        *,
        profile_id: Optional[str] = None,
        name: str = "",
        preferences: Optional[dict] = None,
        notes: str = "",
    ) -> dict:
        if profile_id and profile_id in self.profiles:
            p = self.profiles[profile_id]
            if name:
                p["name"] = name.strip()
            if notes is not None:
                p["notes"] = (notes or "").strip()
            if preferences is not None:
                prefs = dict(p.get("preferences") or {})
                prefs.update(_clean_kv(preferences))
                p["preferences"] = prefs
            self.profiles[profile_id] = p
            self._save_profiles()
            return dict(p)
        p = _new_profile(
            name or "User",
            preferences=preferences,
            notes=notes,
            profile_id=profile_id,
        )
        self.profiles[p["id"]] = p
        if not self.active_profile_id:
            self.active_profile_id = p["id"]
        self._save_profiles()
        return dict(p)

    def create_profile_from_text(self, text: str, *, activate: bool = True) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("Empty profile text")

        pref_list = ", ".join(PREF_KEYS)
        explicit_name = _extract_explicit_name(text)
        prompt = (
            "Из описания пользователя собери профиль ассистента.\n"
            "Верни ТОЛЬКО JSON:\n"
            '{"name":"имя профиля",'
            '"notes":"1-2 предложения контекста",'
            f'"preferences":{{"style":"...","format":"...","constraints":"...",'
            '"language":"ru|en","length":"кратко|средне|detailed","emoji":"нет|умеренно"}}}\n'
            f"Поля preferences: {pref_list}.\n"
            "Правила для name:\n"
            "- Если в тексте явно указано Name: / Имя: / My name is / Меня зовут — "
            "скопируй это значение в name БУКВАЛЬНО, без перевода и без украшений.\n"
            "- Не придумывай эпитеты вроде «Аналитичный Kyle» — только само имя.\n"
            "- Если явного имени нет — короткое имя из роли/контекста.\n"
            "Detail level → length. Decision style и Preferences → constraints/style.\n"
        )
        if explicit_name:
            prompt += f"\nЯвное имя из текста (обязательно используй как name): {explicit_name!r}\n"
        prompt += f"\nОписание:\n{text}"

        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты извлекаешь профиль пользователя. Отвечай только JSON. "
                        "Явное Name/Имя важнее твоих формулировок."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = _parse_json_object(raw)
        name = str(parsed.get("name") or "").strip()
        notes = str(parsed.get("notes") or "").strip()
        preferences = parsed.get("preferences")
        if not isinstance(preferences, dict):
            preferences = {}
        preferences = _clean_kv(preferences)

        # Deterministic: explicit Name: always wins over LLM paraphrase
        if explicit_name:
            name = explicit_name
        elif not name:
            first = text.splitlines()[0].strip() if text else "User"
            name = (first[:40] + "…") if len(first) > 40 else first or "User"
        if not notes:
            notes = text if len(text) <= 240 else text[:237] + "…"
        if not any(preferences.get(k) for k in PREF_KEYS):
            preferences = {
                "style": "нейтральный",
                "format": "короткие абзацы",
                "constraints": "",
                "language": "ru",
                "length": "кратко",
                "emoji": "нет",
            }

        usage = getattr(response, "usage", None)
        self.usage_log.append(
            {
                "kind": "create_profile",
                "model": self.model,
                "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                "completion_tokens": getattr(usage, "completion_tokens", None)
                if usage
                else None,
            }
        )
        self._save_settings()

        profile = self.upsert_profile(name=name, preferences=preferences, notes=notes)
        if activate:
            self.set_active_profile(profile["id"], clear_dialog=True)
            profile = self.get_active_profile() or profile
        return dict(profile)

    def delete_profile(self, profile_id: str) -> None:
        pid = (profile_id or "").strip()
        if pid not in self.profiles:
            raise ValueError(f"Unknown profile: {pid}")
        if len(self.profiles) <= 1:
            raise ValueError("Cannot delete the last profile")
        del self.profiles[pid]
        if self.active_profile_id == pid:
            self.active_profile_id = next(iter(self.profiles))
        self._save_profiles()

    def clear_dialog(self) -> None:
        self.messages = []
        self.last_api_messages = []
        self.last_tokens = {}

    def _profile_system_message(self) -> Optional[dict]:
        p = self.get_active_profile()
        if not p:
            return None
        prefs = p.get("preferences") or {}
        lines = [f"Active user profile: {p.get('name') or p.get('id')}"]
        if p.get("notes"):
            lines.append(f"- notes: {p['notes']}")
        for key in PREF_KEYS:
            val = (prefs.get(key) or "").strip()
            if val:
                lines.append(f"- {key}: {val}")
        for key, val in prefs.items():
            if key in PREF_KEYS:
                continue
            val = (val or "").strip()
            if val:
                lines.append(f"- {key}: {val}")
        return {"role": "system", "content": "\n".join(lines)}

    def _dialog_window(self) -> list[dict]:
        return list(self.messages[-self.window_size :])

    def _build_api_messages(self) -> list[dict]:
        out: list[dict] = []
        if self.role:
            out.append({"role": "system", "content": self.role})
        profile_msg = self._profile_system_message()
        if profile_msg:
            out.append(profile_msg)
        out.extend(self._dialog_window())
        return out

    def _estimate_tokens(self, api_messages: list[dict]) -> dict:
        model = self.model
        prompt_estimate = count_messages_tokens(api_messages, model)
        role_msgs = [{"role": "system", "content": self.role}] if self.role else []
        profile = self._profile_system_message()
        dialog = self._dialog_window()
        layers = {
            "role": count_messages_tokens(role_msgs, model) if role_msgs else 0,
            "profile": count_messages_tokens([profile], model) if profile else 0,
            "dialog": count_messages_tokens(dialog, model) if dialog else 0,
        }
        return {
            "model": model,
            "context_limit": self.context_limit,
            "window_size": self.window_size,
            "prompt_estimate": prompt_estimate,
            "over_limit": prompt_estimate > self.context_limit,
            "layers": layers,
            "dialog_messages": len(self.messages),
            "active_profile_id": self.active_profile_id,
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
            "active_profile_id": self.active_profile_id,
            "profiles": self.list_profiles(),
            "active_profile": self.get_active_profile(),
            "messages": list(self.messages),
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
                "profile_id": self.active_profile_id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost,
            }
        )
        self._save_settings()
        self.messages.append({"role": "assistant", "content": reply})
        snap = self.snapshot()
        snap["reply"] = reply
        return snap
