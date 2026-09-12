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

PRICING = {
    "gpt-5.4": {"input_per_mtok": 2.50, "output_per_mtok": 15.00},
    "gpt-5.4-mini": {"input_per_mtok": 0.75, "output_per_mtok": 4.50},
    "gpt-5.4-nano": {"input_per_mtok": 0.20, "output_per_mtok": 1.25},
    "gpt-5.5": {"input_per_mtok": 5.00, "output_per_mtok": 30.00},
    "gpt-4o": {"input_per_mtok": 2.50, "output_per_mtok": 10.00},
}

DEFAULT_CONTEXT_LIMIT = 2048
DEFAULT_KEEP_LAST = 6
DEFAULT_SUMMARIZE_EVERY = 10


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


def _clone_messages(messages: list[dict]) -> list[dict]:
    return [{"role": m["role"], "content": m["content"]} for m in messages]


class Agent:
    """Split compare: full history vs compressed history, same user turns."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4",
        role: str = "",
        history_path: Optional[Path] = None,
        context_limit: int = DEFAULT_CONTEXT_LIMIT,
    ):
        if not api_key or api_key == "sk-your-key-here":
            raise ValueError("OPENAI_API_KEY is missing or placeholder")
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model not allowed: {model}")

        self._client = OpenAI(api_key=api_key)
        self.history_path = Path(history_path) if history_path else Path("history.json")
        self.model = model
        self.role = (role or "").strip()
        self.context_limit = int(context_limit)
        self.usage_log: list[dict] = []

        self.messages_full: list[dict] = []
        self.messages_comp: list[dict] = []
        self.summary = ""
        self.keep_last = DEFAULT_KEEP_LAST
        self.summarize_every = DEFAULT_SUMMARIZE_EVERY
        self.last_summarized_count = 0

        self.last_payload_full: list[dict] = []
        self.last_payload_comp: list[dict] = []
        self.last_tokens_full: dict = {}
        self.last_tokens_comp: dict = {}

        self._load()

    def _with_role(self, msgs: list[dict]) -> list[dict]:
        out: list[dict] = []
        if self.role:
            out.append({"role": "system", "content": self.role})
        out.extend(msgs)
        return out

    def _full_api_messages(self, messages: Optional[list[dict]] = None) -> list[dict]:
        return self._with_role(messages if messages is not None else self.messages_full)

    def _compressed_api_messages(
        self, messages: Optional[list[dict]] = None
    ) -> list[dict]:
        msgs = messages if messages is not None else self.messages_comp
        keep = max(1, int(self.keep_last))
        tail = msgs[-keep:] if msgs else []
        api: list[dict] = []
        if self.role:
            api.append({"role": "system", "content": self.role})
        if self.summary.strip():
            api.append(
                {
                    "role": "system",
                    "content": (
                        "Earlier conversation summary (compressed history):\n"
                        + self.summary.strip()
                    ),
                }
            )
        api.extend(tail)
        return api

    def _side_tokens(
        self,
        *,
        side: str,
        api_messages: list[dict],
        request_estimate: int = 0,
        reply_estimate: int = 0,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        cost_usd=None,
        over_limit: Optional[bool] = None,
    ) -> dict:
        prompt_estimate = count_messages_tokens(api_messages, self.model)
        window_or_limit = self.context_limit
        return {
            "side": side,
            "request_estimate": request_estimate,
            "prompt_estimate": prompt_estimate,
            "reply_estimate": reply_estimate,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "context_limit": window_or_limit,
            "over_limit": (
                over_limit
                if over_limit is not None
                else prompt_estimate > window_or_limit
            ),
            "message_count": len(api_messages),
        }

    def current_token_summary(self) -> dict:
        full_api = self._full_api_messages()
        comp_api = self._compressed_api_messages()
        full = self._side_tokens(side="full", api_messages=full_api)
        comp = self._side_tokens(side="compressed", api_messages=comp_api)
        return {
            "full": {**full, **(self.last_tokens_full or {})},
            "compressed": {**comp, **(self.last_tokens_comp or {})},
            "prompt_estimate_full": full["prompt_estimate"],
            "prompt_estimate_compressed": comp["prompt_estimate"],
            "tokens_saved_estimate": max(
                0, full["prompt_estimate"] - comp["prompt_estimate"]
            ),
            "keep_last": self.keep_last,
            "summarize_every": self.summarize_every,
            "summary_chars": len(self.summary or ""),
            "context_limit": self.context_limit,
        }

    def snapshot(self) -> dict:
        return {
            "model": self.model,
            "role": self.role,
            "messages_full": list(self.messages_full),
            "messages_comp": list(self.messages_comp),
            "summary": self.summary,
            "keep_last": self.keep_last,
            "summarize_every": self.summarize_every,
            "last_summarized_count": self.last_summarized_count,
            "context_limit": self.context_limit,
            "usage_log": list(self.usage_log),
            "tokens": self.current_token_summary(),
            "last_payload_full": list(self.last_payload_full),
            "last_payload_comp": list(self.last_payload_comp),
        }

    def set_model(self, model: str) -> None:
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model not allowed: {model}")
        self.model = model
        self._save()

    def set_role(self, role: str) -> None:
        self.role = (role or "").strip()
        self._save()

    def set_context_limit(self, limit: int) -> None:
        value = int(limit)
        if value < 64:
            raise ValueError("context_limit must be >= 64")
        self.context_limit = value
        self._save()

    def set_keep_last(self, n: int) -> None:
        value = int(n)
        if value < 1:
            raise ValueError("keep_last must be >= 1")
        self.keep_last = value
        self._save()

    def set_summarize_every(self, n: int) -> None:
        value = int(n)
        if value < 2:
            raise ValueError("summarize_every must be >= 2")
        self.summarize_every = value
        self._save()

    def reset(self) -> None:
        self.messages_full = []
        self.messages_comp = []
        self.usage_log = []
        self.summary = ""
        self.last_summarized_count = 0
        self.last_payload_full = []
        self.last_payload_comp = []
        self.last_tokens_full = {}
        self.last_tokens_comp = {}
        self._save()

    def _should_summarize(self) -> bool:
        if len(self.messages_comp) <= self.keep_last:
            return False
        older_len = len(self.messages_comp) - self.keep_last
        if older_len < self.summarize_every:
            return False
        return (older_len - self.last_summarized_count) >= self.summarize_every

    def _summarize_older(self, force: bool = False) -> dict:
        if len(self.messages_comp) <= self.keep_last:
            return {"summarized": False, "reason": "not enough messages"}
        older = self.messages_comp[: -self.keep_last]
        if not force and not self._should_summarize():
            return {"summarized": False, "reason": "threshold not reached"}

        older_text = [f"{m['role']}: {m['content']}" for m in older]
        prev = self.summary.strip() or "(пусто)"
        prompt = (
            "Сжми историю диалога в краткое резюме на русском.\n"
            "Сохрани важные факты, имена, решения и открытые вопросы.\n"
            "Без вступлений — только текст summary.\n\n"
            f"Предыдущее summary:\n{prev}\n\n"
            f"Сообщения для сжатия:\n" + "\n".join(older_text)
        )
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "Ты сжимаешь историю чата в плотное резюме.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        summary_text = completion.choices[0].message.content or ""
        usage = completion.usage
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
        cost = estimate_cost_usd(
            self.model, int(prompt_tokens or 0), int(completion_tokens or 0)
        )
        self.summary = summary_text.strip()
        self.last_summarized_count = len(older)
        self.usage_log.append(
            {
                "turn": len(self.usage_log) + 1,
                "kind": "summarize",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
                "cost_usd": cost,
                "older_messages": len(older),
            }
        )
        self._save()
        return {
            "summarized": True,
            "summary": self.summary,
            "older_messages": len(older),
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost,
            },
        }

    def compress_now(self) -> dict:
        result = self._summarize_older(force=True)
        snap = self.snapshot()
        snap["compress_result"] = result
        return snap

    def _call_side(self, side: str, api_messages: list[dict], request_estimate: int) -> dict:
        tokens_pre = self._side_tokens(
            side=side,
            api_messages=api_messages,
            request_estimate=request_estimate,
        )
        if tokens_pre["over_limit"]:
            return {
                "ok": False,
                "error": (
                    f"{side} overflow: prompt_estimate={tokens_pre['prompt_estimate']} "
                    f"> context_limit={self.context_limit}"
                ),
                "reply": "",
                "tokens": tokens_pre,
                "api_messages": _clone_messages(api_messages),
                "finish_reason": None,
            }

        completion = self._client.chat.completions.create(
            model=self.model,
            messages=api_messages,
        )
        choice = completion.choices[0]
        assistant_text = choice.message.content or ""
        usage = completion.usage
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
        total_tokens = getattr(usage, "total_tokens", None) if usage else None
        reply_estimate = count_text_tokens(assistant_text, self.model)
        cost = estimate_cost_usd(
            self.model,
            int(prompt_tokens or tokens_pre["prompt_estimate"]),
            int(completion_tokens or reply_estimate),
        )
        tokens = self._side_tokens(
            side=side,
            api_messages=api_messages,
            request_estimate=request_estimate,
            reply_estimate=reply_estimate,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            over_limit=False,
        )
        return {
            "ok": True,
            "error": None,
            "reply": assistant_text,
            "tokens": tokens,
            "api_messages": _clone_messages(api_messages),
            "finish_reason": choice.finish_reason,
        }

    def reply(self, user_message: str) -> dict:
        text = (user_message or "").strip()
        if not text:
            raise ValueError("User message is empty")

        request_estimate = count_text_tokens(text, self.model)
        user_item = {"role": "user", "content": text}
        self.messages_full.append(user_item)
        self.messages_comp.append({"role": "user", "content": text})

        full_api = self._full_api_messages()
        comp_api = self._compressed_api_messages()

        full_result = self._call_side("full", full_api, request_estimate)
        comp_result = self._call_side("compressed", comp_api, request_estimate)

        if full_result["ok"]:
            self.messages_full.append(
                {"role": "assistant", "content": full_result["reply"]}
            )
        else:
            self.messages_full.append(
                {
                    "role": "assistant",
                    "content": f"⚠️ {full_result['error']}",
                }
            )

        if comp_result["ok"]:
            self.messages_comp.append(
                {"role": "assistant", "content": comp_result["reply"]}
            )
        else:
            self.messages_comp.append(
                {
                    "role": "assistant",
                    "content": f"⚠️ {comp_result['error']}",
                }
            )

        if not full_result["ok"] and not comp_result["ok"]:
            # keep the failed turn visible; still raise so UI shows global error too
            self._save()
            raise ContextOverflowError(
                "both sides overflowed context_limit",
                {
                    "full": full_result["tokens"],
                    "compressed": comp_result["tokens"],
                    "messages_full": list(self.messages_full),
                    "messages_comp": list(self.messages_comp),
                },
            )

        self.last_payload_full = full_result["api_messages"]
        self.last_payload_comp = comp_result["api_messages"]
        self.last_tokens_full = full_result["tokens"]
        self.last_tokens_comp = comp_result["tokens"]

        saved = 0
        if full_result["ok"] and comp_result["ok"]:
            saved = max(
                0,
                full_result["tokens"]["prompt_estimate"]
                - comp_result["tokens"]["prompt_estimate"],
            )

        self.usage_log.append(
            {
                "turn": len(self.usage_log) + 1,
                "kind": "chat_compare",
                "full_prompt_tokens": full_result["tokens"].get("prompt_tokens"),
                "comp_prompt_tokens": comp_result["tokens"].get("prompt_tokens"),
                "full_prompt_estimate": full_result["tokens"].get("prompt_estimate"),
                "comp_prompt_estimate": comp_result["tokens"].get("prompt_estimate"),
                "tokens_saved_estimate": saved,
                "full_cost_usd": full_result["tokens"].get("cost_usd"),
                "comp_cost_usd": comp_result["tokens"].get("cost_usd"),
                "full_ok": full_result["ok"],
                "comp_ok": comp_result["ok"],
            }
        )

        compress_info = {"summarized": False}
        if comp_result["ok"] and self._should_summarize():
            try:
                compress_info = self._summarize_older(force=False)
            except Exception as exc:
                compress_info = {"summarized": False, "error": str(exc)}

        self._save()
        snap = self.snapshot()
        snap.update(
            {
                "full": full_result,
                "compressed": comp_result,
                "compress": compress_info,
                "request_estimate": request_estimate,
            }
        )
        return snap

    def _load_message_list(self, raw: Any) -> list[dict]:
        loaded = []
        for item in raw or []:
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and isinstance(content, str):
                loaded.append({"role": role, "content": content})
        return loaded

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

        limit = data.get("context_limit")
        if isinstance(limit, int) and limit >= 64:
            self.context_limit = limit

        keep = data.get("keep_last")
        if isinstance(keep, int) and keep >= 1:
            self.keep_last = keep
        every = data.get("summarize_every")
        if isinstance(every, int) and every >= 2:
            self.summarize_every = every
        self.summary = (data.get("summary") or "").strip()
        last = data.get("last_summarized_count")
        if isinstance(last, int) and last >= 0:
            self.last_summarized_count = last

        if "messages_full" in data or "messages_comp" in data:
            self.messages_full = self._load_message_list(data.get("messages_full"))
            self.messages_comp = self._load_message_list(data.get("messages_comp"))
        else:
            # migrate legacy single transcript into both lanes
            legacy = self._load_message_list(data.get("messages"))
            self.messages_full = list(legacy)
            self.messages_comp = list(legacy)

        self.last_payload_full = self._load_message_list(data.get("last_payload_full"))
        self.last_payload_comp = self._load_message_list(data.get("last_payload_comp"))
        if isinstance(data.get("last_tokens_full"), dict):
            self.last_tokens_full = data["last_tokens_full"]
        if isinstance(data.get("last_tokens_comp"), dict):
            self.last_tokens_comp = data["last_tokens_comp"]

        log: list[dict[str, Any]] = []
        for item in data.get("usage_log") or []:
            if isinstance(item, dict):
                log.append(item)
        self.usage_log = log

    def _save(self) -> None:
        payload = {
            "model": self.model,
            "role": self.role,
            "context_limit": self.context_limit,
            "keep_last": self.keep_last,
            "summarize_every": self.summarize_every,
            "summary": self.summary,
            "last_summarized_count": self.last_summarized_count,
            "messages_full": self.messages_full,
            "messages_comp": self.messages_comp,
            "last_payload_full": self.last_payload_full,
            "last_payload_comp": self.last_payload_comp,
            "last_tokens_full": self.last_tokens_full,
            "last_tokens_comp": self.last_tokens_comp,
            "usage_log": self.usage_log,
        }
        self.history_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
