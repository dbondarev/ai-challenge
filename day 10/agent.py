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

STRATEGIES = {"sliding", "facts", "branching"}
FACT_KEYS = ("goal", "constraints", "preferences", "decisions", "other")

DEFAULT_CONTEXT_LIMIT = 2048
DEFAULT_WINDOW_SIZE = 8
DEFAULT_FACTS_WINDOW = 6


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


def _new_branch(name: str, messages: Optional[list] = None, created_from=None, checkpoint_index=None):
    return {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "messages": list(messages or []),
        "created_from": created_from,
        "checkpoint_index": checkpoint_index,
    }


class Agent:
    """Agent with three context strategies: sliding, facts, branching."""

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

        self.strategy = "sliding"
        self.window_size = DEFAULT_WINDOW_SIZE
        self.facts_window = DEFAULT_FACTS_WINDOW
        self.messages_full: list[dict] = []
        self.facts: dict[str, str] = {}

        main = _new_branch("main")
        self.branches: dict[str, dict] = {main["id"]: main}
        self.active_branch_id = main["id"]
        self.checkpoint_index: Optional[int] = None

        self._load()

    # --- branch helpers ---

    def _active_branch(self) -> dict:
        return self.branches[self.active_branch_id]

    def _ui_messages(self) -> list[dict]:
        if self.strategy == "branching":
            return list(self._active_branch()["messages"])
        return list(self.messages_full)

    def _append_message(self, role: str, content: str) -> None:
        item = {"role": role, "content": content}
        if self.strategy == "branching":
            self._active_branch()["messages"].append(item)
        else:
            self.messages_full.append(item)

    def _pop_last_user(self) -> None:
        msgs = (
            self._active_branch()["messages"]
            if self.strategy == "branching"
            else self.messages_full
        )
        if msgs and msgs[-1]["role"] == "user":
            msgs.pop()

    # --- API context builders ---

    def _with_role(self, msgs: list[dict]) -> list[dict]:
        out: list[dict] = []
        if self.role:
            out.append({"role": "system", "content": self.role})
        out.extend(msgs)
        return out

    def build_api_messages(self) -> list[dict]:
        if self.strategy == "sliding":
            window = self.messages_full[-self.window_size :]
            return self._with_role(window)

        if self.strategy == "facts":
            api: list[dict] = []
            if self.role:
                api.append({"role": "system", "content": self.role})
            if self.facts:
                lines = [f"- {k}: {v}" for k, v in self.facts.items() if v]
                api.append(
                    {
                        "role": "system",
                        "content": "Known facts (sticky memory):\n" + "\n".join(lines),
                    }
                )
            api.extend(self.messages_full[-self.facts_window :])
            return api

        # branching
        return self._with_role(list(self._active_branch()["messages"]))

    def build_full_api_messages(self) -> list[dict]:
        if self.strategy == "branching":
            return self._with_role(list(self._active_branch()["messages"]))
        return self._with_role(list(self.messages_full))

    def token_report(self, request_text: str = "") -> dict:
        api_msgs = self.build_api_messages()
        full_msgs = self.build_full_api_messages()
        prompt_estimate = count_messages_tokens(api_msgs, self.model)
        prompt_estimate_if_full = count_messages_tokens(full_msgs, self.model)
        return {
            "request_estimate": count_text_tokens(request_text, self.model)
            if request_text
            else 0,
            "prompt_estimate": prompt_estimate,
            "prompt_estimate_if_full": prompt_estimate_if_full,
            "tokens_saved_vs_full": max(0, prompt_estimate_if_full - prompt_estimate),
            "context_limit": self.context_limit,
            "over_limit": prompt_estimate > self.context_limit,
            "strategy": self.strategy,
            "window_size": self.window_size,
            "facts_window": self.facts_window,
            "facts_count": len(self.facts),
        }

    def snapshot(self) -> dict:
        return {
            "model": self.model,
            "role": self.role,
            "strategy": self.strategy,
            "window_size": self.window_size,
            "facts_window": self.facts_window,
            "context_limit": self.context_limit,
            "messages": self._ui_messages(),
            "messages_full_count": len(self.messages_full),
            "facts": dict(self.facts),
            "branches": {
                bid: {
                    "id": b["id"],
                    "name": b["name"],
                    "created_from": b.get("created_from"),
                    "checkpoint_index": b.get("checkpoint_index"),
                    "message_count": len(b["messages"]),
                }
                for bid, b in self.branches.items()
            },
            "active_branch_id": self.active_branch_id,
            "checkpoint_index": self.checkpoint_index,
            "usage_log": list(self.usage_log),
            "tokens": self.token_report(),
        }

    # --- setters ---

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

    def set_strategy(self, strategy: str) -> None:
        if strategy not in STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy}")
        self.strategy = strategy
        self._save()

    def set_window_size(self, n: int) -> None:
        value = int(n)
        if value < 1:
            raise ValueError("window_size must be >= 1")
        self.window_size = value
        self._save()

    def set_facts_window(self, n: int) -> None:
        value = int(n)
        if value < 1:
            raise ValueError("facts_window must be >= 1")
        self.facts_window = value
        self._save()

    def set_facts(self, facts: dict) -> None:
        cleaned: dict[str, str] = {}
        for key, value in (facts or {}).items():
            key_s = str(key).strip()
            val_s = str(value).strip()
            if key_s and val_s:
                cleaned[key_s] = val_s
        self.facts = cleaned
        self._save()

    def reset(self) -> None:
        self.messages_full = []
        self.facts = {}
        self.usage_log = []
        main = _new_branch("main")
        self.branches = {main["id"]: main}
        self.active_branch_id = main["id"]
        self.checkpoint_index = None
        self._save()

    # --- facts extraction ---

    def _extract_facts(self, user_text: str) -> dict:
        existing = json.dumps(self.facts, ensure_ascii=False)
        prompt = (
            "Обнови словарь фактов диалога. Верни ТОЛЬКО JSON-объект с ключами "
            f"{list(FACT_KEYS)}. Пустые значения опусти. Не выдумывай.\n\n"
            f"Текущие facts:\n{existing}\n\n"
            f"Новое сообщение пользователя:\n{user_text}"
        )
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "Ты извлекаешь факты в JSON. Без markdown.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content or "{}"
        usage = completion.usage
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
        cost = estimate_cost_usd(
            self.model, int(prompt_tokens or 0), int(completion_tokens or 0)
        )
        self.usage_log.append(
            {
                "turn": len(self.usage_log) + 1,
                "kind": "facts_extract",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
                "cost_usd": cost,
            }
        )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(match.group(0)) if match else {}

        merged = dict(self.facts)
        if isinstance(data, dict):
            for key in FACT_KEYS:
                if key in data and str(data[key]).strip():
                    merged[key] = str(data[key]).strip()
            for key, value in data.items():
                if key not in FACT_KEYS and str(value).strip():
                    merged[str(key)] = str(value).strip()
        self.facts = merged
        return {"facts": dict(self.facts), "raw": raw}

    def refresh_facts(self) -> dict:
        # Use last user message or whole transcript snippet
        user_bits = [
            m["content"] for m in self._ui_messages() if m["role"] == "user"
        ]
        text = user_bits[-1] if user_bits else "(нет сообщений)"
        result = self._extract_facts(text)
        self._save()
        snap = self.snapshot()
        snap["facts_refresh"] = result
        return snap

    # --- branching ---

    def set_checkpoint(self) -> dict:
        msgs = self._active_branch()["messages"]
        self.checkpoint_index = len(msgs)
        self._active_branch()["checkpoint_index"] = self.checkpoint_index
        self._save()
        return self.snapshot()

    def fork_branch(self, name: str = "") -> dict:
        src = self._active_branch()
        idx = self.checkpoint_index
        if idx is None:
            idx = len(src["messages"])
        idx = max(0, min(int(idx), len(src["messages"])))
        branch_name = (name or "").strip() or f"branch-{len(self.branches) + 1}"
        new = _new_branch(
            branch_name,
            messages=src["messages"][:idx],
            created_from=src["id"],
            checkpoint_index=idx,
        )
        self.branches[new["id"]] = new
        self.active_branch_id = new["id"]
        self.checkpoint_index = len(new["messages"])
        self._save()
        return self.snapshot()

    def switch_branch(self, branch_id: str) -> dict:
        if branch_id not in self.branches:
            raise ValueError(f"Unknown branch: {branch_id}")
        self.active_branch_id = branch_id
        self.checkpoint_index = self.branches[branch_id].get("checkpoint_index")
        self._save()
        return self.snapshot()

    # --- chat ---

    def reply(self, user_message: str) -> dict:
        text = (user_message or "").strip()
        if not text:
            raise ValueError("User message is empty")

        request_estimate = count_text_tokens(text, self.model)
        self._append_message("user", text)

        facts_info = None
        if self.strategy == "facts":
            try:
                facts_info = self._extract_facts(text)
            except Exception as exc:
                facts_info = {"error": str(exc)}

        api_messages = self.build_api_messages()
        tokens_pre = self.token_report(text)
        tokens_pre["request_estimate"] = request_estimate
        tokens_pre["prompt_estimate"] = count_messages_tokens(api_messages, self.model)
        tokens_pre["over_limit"] = tokens_pre["prompt_estimate"] > self.context_limit

        if tokens_pre["over_limit"]:
            self._pop_last_user()
            raise ContextOverflowError(
                (
                    f"context overflow: prompt_estimate={tokens_pre['prompt_estimate']} "
                    f"> context_limit={self.context_limit}"
                ),
                tokens_pre,
            )

        try:
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=api_messages,
            )
        except Exception:
            self._pop_last_user()
            raise

        choice = completion.choices[0]
        assistant_text = choice.message.content or ""
        self._append_message("assistant", assistant_text)

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

        tokens = self.token_report()
        tokens.update(
            {
                "request_estimate": request_estimate,
                "prompt_estimate": tokens_pre["prompt_estimate"],
                "reply_estimate": reply_estimate,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost,
                "over_limit": False,
            }
        )

        self.usage_log.append(
            {
                "turn": len(self.usage_log) + 1,
                "kind": "chat",
                "strategy": self.strategy,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "prompt_estimate": tokens_pre["prompt_estimate"],
                "prompt_estimate_if_full": tokens.get("prompt_estimate_if_full"),
                "tokens_saved_vs_full": tokens.get("tokens_saved_vs_full"),
                "cost_usd": cost,
            }
        )
        self._save()

        return {
            "reply": assistant_text,
            "model": self.model,
            "role": self.role,
            "strategy": self.strategy,
            "finish_reason": choice.finish_reason,
            "messages": self._ui_messages(),
            "facts": dict(self.facts),
            "tokens": tokens,
            "usage_log": list(self.usage_log),
            "facts_update": facts_info,
            "active_branch_id": self.active_branch_id,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        }

    # --- persistence ---

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
        strategy = data.get("strategy")
        if strategy in STRATEGIES:
            self.strategy = strategy

        limit = data.get("context_limit")
        if isinstance(limit, int) and limit >= 64:
            self.context_limit = limit
        ws = data.get("window_size")
        if isinstance(ws, int) and ws >= 1:
            self.window_size = ws
        fw = data.get("facts_window")
        if isinstance(fw, int) and fw >= 1:
            self.facts_window = fw

        facts = data.get("facts")
        if isinstance(facts, dict):
            self.facts = {
                str(k): str(v)
                for k, v in facts.items()
                if str(k).strip() and str(v).strip()
            }

        full = []
        for item in data.get("messages_full") or data.get("messages") or []:
            if item.get("role") in ("user", "assistant") and isinstance(
                item.get("content"), str
            ):
                full.append({"role": item["role"], "content": item["content"]})
        self.messages_full = full

        branches_raw = data.get("branches")
        if isinstance(branches_raw, dict) and branches_raw:
            loaded_branches = {}
            for bid, b in branches_raw.items():
                msgs = []
                for item in b.get("messages") or []:
                    if item.get("role") in ("user", "assistant") and isinstance(
                        item.get("content"), str
                    ):
                        msgs.append(
                            {"role": item["role"], "content": item["content"]}
                        )
                loaded_branches[bid] = {
                    "id": bid,
                    "name": b.get("name") or bid,
                    "messages": msgs,
                    "created_from": b.get("created_from"),
                    "checkpoint_index": b.get("checkpoint_index"),
                }
            self.branches = loaded_branches
            active = data.get("active_branch_id")
            if active in self.branches:
                self.active_branch_id = active
            else:
                self.active_branch_id = next(iter(self.branches))
        cp = data.get("checkpoint_index")
        if isinstance(cp, int):
            self.checkpoint_index = cp

        log = []
        for item in data.get("usage_log") or []:
            if isinstance(item, dict):
                log.append(item)
        self.usage_log = log

    def _save(self) -> None:
        payload = {
            "model": self.model,
            "role": self.role,
            "strategy": self.strategy,
            "context_limit": self.context_limit,
            "window_size": self.window_size,
            "facts_window": self.facts_window,
            "facts": self.facts,
            "messages_full": self.messages_full,
            "branches": self.branches,
            "active_branch_id": self.active_branch_id,
            "checkpoint_index": self.checkpoint_index,
            "usage_log": self.usage_log,
        }
        self.history_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )




class StrategyCompare:
    """Compare runner: sliding / facts / branching, with A/B fork + timeline rows."""

    BASE_LANES = ("sliding", "facts", "branching")
    FORK_LANES = ("sliding", "facts", "branching_a", "branching_b")

    def __init__(
        self,
        api_key: str,
        history_path: Optional[Path] = None,
        model: str = "gpt-5.4",
        role: str = "",
        context_limit: int = DEFAULT_CONTEXT_LIMIT,
        window_size: int = DEFAULT_WINDOW_SIZE,
        facts_window: int = DEFAULT_FACTS_WINDOW,
    ):
        if not api_key or api_key == "sk-your-key-here":
            raise ValueError("OPENAI_API_KEY is missing or placeholder")
        self._client = OpenAI(api_key=api_key)
        self.history_path = (
            Path(history_path) if history_path else Path("compare_history.json")
        )
        self.model = model if model in ALLOWED_MODELS else "gpt-5.4"
        self.role = (role or "").strip()
        self.context_limit = int(context_limit)
        self.window_size = int(window_size)
        self.facts_window = int(facts_window)
        self.usage_log: list[dict] = []
        self.timeline: list[dict] = []
        self.forked = False
        self.checkpoint_messages: list[dict] = []
        self.scenario_step = 0
        self.lanes: dict[str, dict] = {}
        self._init_lanes()
        self._load()

    def _empty_lane(self, with_facts: bool = False) -> dict:
        lane = {"messages": [], "last_payload": [], "last_tokens": {}}
        if with_facts:
            lane["facts"] = {}
        return lane

    def _init_lanes(self) -> None:
        self.lanes = {
            "sliding": self._empty_lane(),
            "facts": self._empty_lane(with_facts=True),
            "branching": self._empty_lane(),
        }
        self.forked = False
        self.checkpoint_messages = []

    @property
    def active_lane_ids(self) -> tuple:
        return self.FORK_LANES if self.forked else self.BASE_LANES

    def _with_role(self, msgs: list[dict], facts: Optional[dict] = None) -> list[dict]:
        out: list[dict] = []
        if self.role:
            out.append({"role": "system", "content": self.role})
        if facts:
            lines = [f"- {k}: {v}" for k, v in facts.items() if v]
            if lines:
                out.append(
                    {
                        "role": "system",
                        "content": "Known facts (sticky memory):\n" + "\n".join(lines),
                    }
                )
        out.extend(msgs)
        return out

    def _build_api(self, lane_id: str) -> list[dict]:
        lane = self.lanes[lane_id]
        msgs = lane["messages"]
        if lane_id == "sliding":
            return self._with_role(msgs[-self.window_size :])
        if lane_id == "facts":
            return self._with_role(
                msgs[-self.facts_window :], facts=lane.get("facts")
            )
        return self._with_role(list(msgs))

    def _build_full(self, lane_id: str) -> list[dict]:
        lane = self.lanes[lane_id]
        if lane_id == "facts":
            return self._with_role(list(lane["messages"]), facts=lane.get("facts"))
        return self._with_role(list(lane["messages"]))

    def _lane_tokens(self, lane_id: str, request_estimate: int = 0, **extra) -> dict:
        api = self._build_api(lane_id)
        full = self._build_full(lane_id)
        prompt_estimate = count_messages_tokens(api, self.model)
        prompt_full = count_messages_tokens(full, self.model)
        tokens = {
            "strategy": lane_id,
            "request_estimate": request_estimate,
            "prompt_estimate": prompt_estimate,
            "prompt_estimate_if_full": prompt_full,
            "tokens_saved_vs_full": max(0, prompt_full - prompt_estimate),
            "context_limit": self.context_limit,
            "over_limit": prompt_estimate > self.context_limit,
            "message_count": len(api),
            "transcript_count": len(self.lanes[lane_id]["messages"]),
        }
        tokens.update(extra)
        return tokens

    def snapshot(self) -> dict:
        sides = {}
        for lid in self.active_lane_ids:
            if lid not in self.lanes:
                continue
            lane = self.lanes[lid]
            base = self._lane_tokens(lid)
            merged = {**base, **(lane.get("last_tokens") or {})}
            sides[lid] = {
                "messages": list(lane["messages"]),
                "facts": dict(lane.get("facts") or {}),
                "last_payload": list(lane.get("last_payload") or []),
                "tokens": merged,
            }
        return {
            "model": self.model,
            "role": self.role,
            "context_limit": self.context_limit,
            "window_size": self.window_size,
            "facts_window": self.facts_window,
            "forked": self.forked,
            "columns": list(self.active_lane_ids),
            "sides": sides,
            "timeline": list(self.timeline),
            "scenario_step": self.scenario_step,
            "usage_log": list(self.usage_log),
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

    def set_window_size(self, n: int) -> None:
        value = int(n)
        if value < 1:
            raise ValueError("window_size must be >= 1")
        self.window_size = value
        self._save()

    def set_facts_window(self, n: int) -> None:
        value = int(n)
        if value < 1:
            raise ValueError("facts_window must be >= 1")
        self.facts_window = value
        self._save()

    def reset(self) -> None:
        self._init_lanes()
        self.usage_log = []
        self.timeline = []
        self.scenario_step = 0
        self._save()

    def _resolve_targets(self, targets: list[str]) -> list[str]:
        out = []
        for t in targets:
            if t == "branching" and self.forked:
                # shared turn after fork → both branches
                out.extend(["branching_a", "branching_b"])
            elif t in self.lanes:
                out.append(t)
            elif t == "branching" and not self.forked:
                out.append("branching")
        # unique preserve order
        seen = set()
        uniq = []
        for x in out:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        return uniq

    def _extract_facts_for_lane(self, user_text: str) -> dict:
        lane = self.lanes["facts"]
        existing = json.dumps(lane.get("facts") or {}, ensure_ascii=False)
        prompt = (
            "Обнови словарь фактов диалога. Верни ТОЛЬКО JSON-объект с ключами "
            f"{list(FACT_KEYS)}. Пустые значения опусти. Не выдумывай.\n\n"
            f"Текущие facts:\n{existing}\n\n"
            f"Новое сообщение пользователя:\n{user_text}"
        )
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "Ты извлекаешь факты в JSON. Без markdown.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content or "{}"
        usage = completion.usage
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
        cost = estimate_cost_usd(
            self.model, int(prompt_tokens or 0), int(completion_tokens or 0)
        )
        self.usage_log.append(
            {
                "turn": len(self.usage_log) + 1,
                "kind": "facts_extract",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost,
            }
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(match.group(0)) if match else {}
        merged = dict(lane.get("facts") or {})
        if isinstance(data, dict):
            for key in FACT_KEYS:
                if key in data and str(data[key]).strip():
                    merged[key] = str(data[key]).strip()
            for key, value in data.items():
                if key not in FACT_KEYS and str(value).strip():
                    merged[str(key)] = str(value).strip()
        lane["facts"] = merged
        return {"facts": dict(merged), "raw": raw}

    def _call_lane(self, lane_id: str, request_estimate: int) -> dict:
        api_messages = self._build_api(lane_id)
        tokens_pre = self._lane_tokens(lane_id, request_estimate=request_estimate)
        payload = [{"role": m["role"], "content": m["content"]} for m in api_messages]

        if tokens_pre["over_limit"]:
            return {
                "ok": False,
                "error": (
                    f"{lane_id} overflow: prompt_estimate={tokens_pre['prompt_estimate']} "
                    f"> context_limit={self.context_limit}"
                ),
                "reply": "",
                "tokens": tokens_pre,
                "api_messages": payload,
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
        tokens = self._lane_tokens(
            lane_id,
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
            "api_messages": payload,
            "finish_reason": choice.finish_reason,
        }

    def checkpoint(self) -> dict:
        src = "branching" if not self.forked else "branching_a"
        if src not in self.lanes:
            src = "branching"
        self.checkpoint_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in self.lanes[src]["messages"]
        ]
        row = {
            "kind": "checkpoint",
            "label": "Checkpoint",
            "prompt": None,
            "targets": [],
            "cells": {},
            "note": f"Saved {len(self.checkpoint_messages)} messages",
        }
        self.timeline.append(row)
        self._save()
        snap = self.snapshot()
        snap["last_row"] = row
        return snap

    def fork(self, names: Optional[dict] = None) -> dict:
        names = names or {"A": "A — premium", "B": "B — mass"}
        base_msgs = self.checkpoint_messages or list(
            self.lanes.get("branching", {}).get("messages") or []
        )
        clone = lambda: [
            {"role": m["role"], "content": m["content"]} for m in base_msgs
        ]
        if "branching" in self.lanes:
            del self.lanes["branching"]
        self.lanes["branching_a"] = self._empty_lane()
        self.lanes["branching_b"] = self._empty_lane()
        self.lanes["branching_a"]["messages"] = clone()
        self.lanes["branching_b"]["messages"] = clone()
        self.lanes["branching_a"]["name"] = names.get("A") or "A"
        self.lanes["branching_b"]["name"] = names.get("B") or "B"
        self.forked = True
        row = {
            "kind": "fork",
            "label": "Fork",
            "prompt": None,
            "targets": [],
            "cells": {},
            "note": f"Forked into {names.get('A')} / {names.get('B')} from checkpoint ({len(base_msgs)} msgs)",
        }
        self.timeline.append(row)
        self._save()
        snap = self.snapshot()
        snap["last_row"] = row
        return snap

    def reply_targets(
        self,
        user_message: str,
        targets: Optional[list] = None,
        label: str = "",
        step_id: str = "",
    ) -> dict:
        text = (user_message or "").strip()
        if not text:
            raise ValueError("User message is empty")
        raw_targets = targets or list(self.active_lane_ids)
        resolved = self._resolve_targets(list(raw_targets))
        if not resolved:
            raise ValueError("No valid targets for reply")

        request_estimate = count_text_tokens(text, self.model)
        for lid in resolved:
            self.lanes[lid]["messages"].append({"role": "user", "content": text})

        facts_info = None
        if "facts" in resolved:
            try:
                facts_info = self._extract_facts_for_lane(text)
            except Exception as exc:
                facts_info = {"error": str(exc)}

        results = {}
        cells = {lid: None for lid in self.active_lane_ids}
        for lid in resolved:
            try:
                result = self._call_lane(lid, request_estimate)
            except Exception as exc:
                result = {
                    "ok": False,
                    "error": str(exc),
                    "reply": "",
                    "tokens": self._lane_tokens(lid, request_estimate=request_estimate),
                    "api_messages": self._build_api(lid),
                }
            results[lid] = result
            if result["ok"]:
                self.lanes[lid]["messages"].append(
                    {"role": "assistant", "content": result["reply"]}
                )
            else:
                self.lanes[lid]["messages"].append(
                    {"role": "assistant", "content": f"⚠️ {result['error']}"}
                )
            self.lanes[lid]["last_payload"] = result["api_messages"]
            self.lanes[lid]["last_tokens"] = result["tokens"]
            cells[lid] = {
                "user": text,
                "assistant": result["reply"] if result["ok"] else f"⚠️ {result['error']}",
                "ok": result["ok"],
                "tokens": result["tokens"],
                "api_messages": result["api_messages"],
            }

        row = {
            "kind": "chat",
            "id": step_id or f"row-{len(self.timeline)+1}",
            "label": label or "",
            "prompt": text,
            "targets": resolved,
            "cells": cells,
        }
        self.timeline.append(row)

        self.usage_log.append(
            {
                "turn": len(self.usage_log) + 1,
                "kind": "chat_compare",
                "targets": resolved,
                "prompt_preview": text[:80],
                **{
                    f"{lid}_prompt_estimate": results[lid]["tokens"].get("prompt_estimate")
                    for lid in results
                },
                **{
                    f"{lid}_cost_usd": results[lid]["tokens"].get("cost_usd")
                    for lid in results
                },
            }
        )
        self._save()
        snap = self.snapshot()
        snap["results"] = results
        snap["facts_update"] = facts_info
        snap["last_row"] = row
        snap["request_estimate"] = request_estimate
        return snap

    def reply(self, user_message: str) -> dict:
        # manual compare send → all active columns
        return self.reply_targets(user_message, targets=list(self.active_lane_ids))

    def _load_msgs(self, raw) -> list[dict]:
        out = []
        for item in raw or []:
            if item.get("role") in ("user", "assistant") and isinstance(
                item.get("content"), str
            ):
                out.append({"role": item["role"], "content": item["content"]})
        return out

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
        ws = data.get("window_size")
        if isinstance(ws, int) and ws >= 1:
            self.window_size = ws
        fw = data.get("facts_window")
        if isinstance(fw, int) and fw >= 1:
            self.facts_window = fw
        self.forked = bool(data.get("forked"))
        self.checkpoint_messages = self._load_msgs(data.get("checkpoint_messages"))
        self.scenario_step = int(data.get("scenario_step") or 0)
        self.timeline = list(data.get("timeline") or [])
        sides = data.get("sides") or {}
        self.lanes = {}
        lane_ids = self.FORK_LANES if self.forked else self.BASE_LANES
        # also load whatever sides exist
        for lid in set(list(lane_ids) + list(sides.keys())):
            side = sides.get(lid) or {}
            with_facts = lid == "facts"
            self.lanes[lid] = self._empty_lane(with_facts=with_facts)
            self.lanes[lid]["messages"] = self._load_msgs(side.get("messages"))
            self.lanes[lid]["last_payload"] = self._load_msgs(side.get("last_payload"))
            if isinstance(side.get("last_tokens"), dict):
                self.lanes[lid]["last_tokens"] = side["last_tokens"]
            if with_facts and isinstance(side.get("facts"), dict):
                self.lanes[lid]["facts"] = {
                    str(k): str(v)
                    for k, v in side["facts"].items()
                    if str(k).strip() and str(v).strip()
                }
            if side.get("name"):
                self.lanes[lid]["name"] = side["name"]
        if not self.lanes:
            self._init_lanes()
        log = []
        for item in data.get("usage_log") or []:
            if isinstance(item, dict):
                log.append(item)
        self.usage_log = log

    def _save(self) -> None:
        sides = {}
        for lid, lane in self.lanes.items():
            sides[lid] = {
                "messages": lane["messages"],
                "last_payload": lane.get("last_payload") or [],
                "last_tokens": lane.get("last_tokens") or {},
            }
            if "facts" in lane:
                sides[lid]["facts"] = lane.get("facts") or {}
            if lane.get("name"):
                sides[lid]["name"] = lane["name"]
        payload = {
            "model": self.model,
            "role": self.role,
            "context_limit": self.context_limit,
            "window_size": self.window_size,
            "facts_window": self.facts_window,
            "forked": self.forked,
            "checkpoint_messages": self.checkpoint_messages,
            "scenario_step": self.scenario_step,
            "timeline": self.timeline,
            "sides": sides,
            "usage_log": self.usage_log,
        }
        self.history_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
