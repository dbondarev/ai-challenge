from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
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

DEFAULT_WINDOW_SIZE = 40

STAGES = ("idle", "planning", "execution", "validation", "done")

STAGE_LABELS = {
    "idle": "Ожидание",
    "planning": "Планирование",
    "execution": "Исполнение",
    "validation": "Проверка",
    "done": "Готово",
}

TRANSITIONS = {
    "idle": {"planning"},
    "planning": {"execution", "idle"},
    "execution": {"validation", "planning"},
    "validation": {"done", "execution"},
    "done": {"idle", "planning"},
}

# Primary forward path for "next stage" button
FORWARD = {
    "idle": "planning",
    "planning": "execution",
    "execution": "validation",
    "validation": "done",
}

STAGE_DEFAULTS = {
    "idle": {"step": "await_start", "expected_action": "user_starts_task"},
    "planning": {
        "step": "clarify_scope",
        "expected_action": "user_confirms_goal_and_constraints",
    },
    "execution": {
        "step": "do_work",
        "expected_action": "user_or_agent_produces_deliverable",
    },
    "validation": {
        "step": "check_result",
        "expected_action": "user_accepts_or_requests_rework",
    },
    "done": {"step": "complete", "expected_action": "none_or_start_new_task"},
}


class ContextOverflowError(ValueError):
    def __init__(self, message: str, tokens: dict):
        super().__init__(message)
        self.tokens = tokens


class InvalidTransitionError(ValueError):
    pass


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _title_from_brief(brief: str) -> str:
    first = (brief or "").strip().splitlines()[0].strip() if brief else ""
    first = re.sub(r"^(задача|task|title|название)\s*[:\-–]\s*", "", first, flags=re.I)
    if not first:
        return "Новая задача"
    return (first[:72] + "…") if len(first) > 72 else first


def _new_task(brief: str, title: str = "") -> dict:
    d = STAGE_DEFAULTS["planning"]
    tid = str(uuid.uuid4())[:8]
    title = (title or "").strip() or _title_from_brief(brief)
    return {
        "task_id": tid,
        "title": title,
        "brief": (brief or "").strip(),
        "stage": "planning",
        "step": d["step"],
        "expected_action": d["expected_action"],
        "paused": False,
        "pause_reason": "",
        "summary": (brief or "").strip()[:800],
        "context": {},
        "messages": [],
        "history": [
            {
                "at": _now(),
                "event": "created",
                "stage": "planning",
                "step": d["step"],
                "detail": "task created from brief",
            }
        ],
        "created_at": _now(),
        "updated_at": _now(),
    }


class Agent:
    """Multi-task FSM: create / switch / advance / pause / comment. Persisted."""

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
        self.tasks_path = self.base_dir / "tasks.json"
        self.settings_path = self.base_dir / "settings.json"

        default_role = (
            "Ты ассистент с формализованным состоянием задачи (FSM). "
            "Веди задачу по этапам planning → execution → validation → done. "
            "На каждом этапе уточняй у пользователя подтверждение перед переходом. "
            "Если paused=true — не двигай работу, жди resume. "
            "На resume продолжай из summary/brief, не проси пересказывать задачу."
        )
        self.model = model
        self.role = (role or default_role).strip()
        self.window_size = DEFAULT_WINDOW_SIZE
        self.usage_log: list[dict] = []

        self.tasks: dict[str, dict] = {}
        self.active_task_id: str = ""
        self.last_api_messages: list[dict] = []
        self.last_tokens: dict[str, Any] = {}

        self._load_settings()
        self._load_tasks()
        self._migrate_legacy()

    @property
    def context_limit(self) -> int:
        return model_context_window(self.model)

    def _load_settings(self) -> None:
        if not self.settings_path.exists():
            return
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

    def _load_tasks(self) -> None:
        if not self.tasks_path.exists():
            return
        try:
            data = json.loads(self.tasks_path.read_text(encoding="utf-8"))
            raw = data.get("tasks") or {}
            cleaned: dict[str, dict] = {}
            for tid, t in raw.items():
                if not isinstance(t, dict):
                    continue
                task = _new_task(t.get("brief") or t.get("title") or "", t.get("title") or "")
                task.update({k: t.get(k, task[k]) for k in task if k in t})
                task["task_id"] = tid
                task["messages"] = list(t.get("messages") or [])
                task["history"] = list(t.get("history") or [])
                task["context"] = dict(t.get("context") or {})
                task["paused"] = bool(t.get("paused"))
                if task["stage"] not in STAGES:
                    task["stage"] = "planning"
                cleaned[tid] = task
            self.tasks = cleaned
            active = str(data.get("active_task_id") or "")
            self.active_task_id = active if active in cleaned else (
                next(iter(cleaned)) if cleaned else ""
            )
        except Exception:
            pass

    def _migrate_legacy(self) -> None:
        """Pull single task_state.json + history.json into tasks.json once."""
        if self.tasks:
            return
        legacy = self.base_dir / "task_state.json"
        hist = self.base_dir / "history.json"
        if not legacy.exists():
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if not data.get("title") and data.get("stage") == "idle":
                return
            brief = data.get("summary") or data.get("title") or "Imported task"
            task = _new_task(brief, data.get("title") or "")
            for k in (
                "stage",
                "step",
                "expected_action",
                "paused",
                "pause_reason",
                "summary",
                "context",
                "history",
            ):
                if k in data:
                    task[k] = data[k]
            if hist.exists():
                h = json.loads(hist.read_text(encoding="utf-8"))
                msgs = h.get("messages") if isinstance(h, dict) else h
                task["messages"] = [
                    {"role": m["role"], "content": m["content"]}
                    for m in (msgs or [])
                    if m.get("role") in ("user", "assistant")
                ]
            self.tasks[task["task_id"]] = task
            self.active_task_id = task["task_id"]
            self._save_tasks()
        except Exception:
            pass

    def _save_tasks(self) -> None:
        if self.active_task_id and self.active_task_id in self.tasks:
            self.tasks[self.active_task_id]["updated_at"] = _now()
        payload = {
            "active_task_id": self.active_task_id,
            "tasks": self.tasks,
        }
        self.tasks_path.write_text(
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

    def active_task(self) -> Optional[dict]:
        return self.tasks.get(self.active_task_id)

    def _log(self, task: dict, event: str, detail: str = "") -> None:
        task["history"].append(
            {
                "at": _now(),
                "event": event,
                "stage": task["stage"],
                "step": task["step"],
                "detail": detail,
            }
        )
        task["history"] = task["history"][-100:]

    def _task_public(self, task: dict) -> dict:
        stage = task["stage"]
        allowed = sorted(TRANSITIONS.get(stage, set()))
        forward = FORWARD.get(stage)
        return {
            **deepcopy(task),
            "stage_label": STAGE_LABELS.get(stage, stage),
            "stages": list(STAGES),
            "stage_labels": dict(STAGE_LABELS),
            "allowed_transitions": allowed,
            "forward_stage": forward if forward in allowed else None,
            "can_pause": stage not in ("idle", "done") and not task["paused"],
            "can_resume": bool(task["paused"]),
            "can_advance": bool(forward) and forward in allowed and not task["paused"],
        }

    def list_tasks_summary(self) -> list[dict]:
        items = []
        for t in sorted(
            self.tasks.values(),
            key=lambda x: x.get("updated_at") or "",
            reverse=True,
        ):
            items.append(
                {
                    "task_id": t["task_id"],
                    "title": t.get("title") or t["task_id"],
                    "stage": t["stage"],
                    "stage_label": STAGE_LABELS.get(t["stage"], t["stage"]),
                    "paused": bool(t.get("paused")),
                    "updated_at": t.get("updated_at") or "",
                    "active": t["task_id"] == self.active_task_id,
                }
            )
        return items

    def select_task(self, task_id: str) -> dict:
        tid = (task_id or "").strip()
        if tid not in self.tasks:
            raise ValueError(f"Unknown task: {tid}")
        self.active_task_id = tid
        self.last_api_messages = []
        self.last_tokens = {}
        self._save_tasks()
        return self.snapshot()

    def delete_task(self, task_id: str) -> dict:
        tid = (task_id or "").strip()
        if tid not in self.tasks:
            raise ValueError(f"Unknown task: {tid}")
        del self.tasks[tid]
        if self.active_task_id == tid:
            self.active_task_id = next(iter(self.tasks), "")
        self._save_tasks()
        return self.snapshot()

    def create_task(self, brief: str) -> dict:
        brief = (brief or "").strip()
        if not brief:
            raise ValueError("Empty task text")

        title = _title_from_brief(brief)
        # optional LLM title polish (short, cheap)
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Верни ТОЛЬКО JSON: {\"title\":\"краткое название задачи до 60 символов\"}",
                    },
                    {"role": "user", "content": brief[:1200]},
                ],
            )
            parsed = _parse_json_object(resp.choices[0].message.content or "")
            if parsed.get("title"):
                title = str(parsed["title"]).strip()[:72] or title
        except Exception:
            pass

        task = _new_task(brief, title)
        task["messages"].append({"role": "user", "content": brief})
        self.tasks[task["task_id"]] = task
        self.active_task_id = task["task_id"]
        self._save_tasks()

        # First agent turn: enter planning, ask for confirmation
        kickoff = (
            "Это новая задача. Ты на этапе planning. "
            "Кратко перескажи, как понял задачу, предложи план этапов "
            "(planning → execution → validation → done) и спроси подтверждение, "
            "чтобы перейти дальше. Не прыгай в execution без согласия."
        )
        return self.reply(kickoff, as_system_nudge=True)

    def transition(self, to_stage: str, *, note: str = "") -> dict:
        task = self.active_task()
        if not task:
            raise ValueError("No active task")
        to_stage = (to_stage or "").strip()
        if to_stage not in STAGES:
            raise InvalidTransitionError(f"Unknown stage: {to_stage}")
        if task["paused"]:
            raise InvalidTransitionError("Задача на паузе — сначала продолжите")
        cur = task["stage"]
        if to_stage != cur and to_stage not in TRANSITIONS.get(cur, set()):
            raise InvalidTransitionError(f"Нельзя: {cur} → {to_stage}")
        defaults = STAGE_DEFAULTS[to_stage]
        prev = cur
        task["stage"] = to_stage
        task["step"] = defaults["step"]
        task["expected_action"] = defaults["expected_action"]
        if to_stage in ("idle", "done"):
            task["paused"] = False
            task["pause_reason"] = ""
        self._log(task, "transition", f"{prev} → {to_stage}" + (f"; {note}" if note else ""))
        self._save_tasks()

        nudge = (
            f"Пользователь подтвердил переход на этап «{STAGE_LABELS.get(to_stage, to_stage)}» "
            f"({to_stage}). Кратко: что делаем на этом этапе и что нужно подтвердить дальше."
        )
        return self.reply(nudge, as_system_nudge=True)

    def advance(self) -> dict:
        task = self.active_task()
        if not task:
            raise ValueError("No active task")
        nxt = FORWARD.get(task["stage"])
        if not nxt or nxt not in TRANSITIONS.get(task["stage"], set()):
            raise InvalidTransitionError("Нет следующего этапа")
        return self.transition(nxt, note="user advanced")

    def pause(self, reason: str = "") -> dict:
        task = self.active_task()
        if not task:
            raise ValueError("No active task")
        if task["stage"] in ("idle", "done"):
            raise InvalidTransitionError("Нечего ставить на паузу")
        if task["paused"]:
            return self.snapshot()
        task["paused"] = True
        task["pause_reason"] = (reason or "").strip() or "paused by user"
        self._log(task, "pause", task["pause_reason"])
        self._save_tasks()
        return self.snapshot()

    def resume(self) -> dict:
        task = self.active_task()
        if not task:
            raise ValueError("No active task")
        if not task["paused"]:
            return self.snapshot()
        was = task["pause_reason"]
        task["paused"] = False
        task["pause_reason"] = ""
        self._log(task, "resume", f"was: {was}")
        self._save_tasks()
        nudge = (
            "Пользователь снял паузу. Продолжи с текущего этапа/шага по summary и истории. "
            "Не проси повторять бриф. Кратко: где мы и что дальше."
        )
        return self.reply(nudge, as_system_nudge=True)

    def comment(self, text: str) -> dict:
        """User comment on current stage — normal chat turn."""
        return self.reply(text, as_system_nudge=False)

    def _fsm_system_message(self, task: dict) -> dict:
        lines = [
            "Task State Machine (authoritative):",
            f"- task_id: {task['task_id']}",
            f"- title: {task.get('title') or ''}",
            f"- stage: {task['stage']} ({STAGE_LABELS.get(task['stage'], '')})",
            f"- step: {task['step']}",
            f"- expected_action: {task['expected_action']}",
            f"- paused: {str(task['paused']).lower()}",
        ]
        if task.get("pause_reason"):
            lines.append(f"- pause_reason: {task['pause_reason']}")
        if task.get("brief"):
            lines.append(f"- brief: {task['brief'][:600]}")
        if task.get("summary"):
            lines.append(f"- summary: {task['summary'][:600]}")
        ctx = task.get("context") or {}
        if ctx:
            lines.append("- context:")
            for k, v in ctx.items():
                lines.append(f"  - {k}: {v}")
        lines.append(
            "Rules: Respect stage. If paused, do not advance. "
            "Ask user confirmation before moving to next stage. "
            "On resume use summary/brief — do not re-ask the whole task."
        )
        return {"role": "system", "content": "\n".join(lines)}

    def _build_api_messages(self, task: dict) -> list[dict]:
        out: list[dict] = []
        if self.role:
            out.append({"role": "system", "content": self.role})
        out.append(self._fsm_system_message(task))
        out.extend(list(task.get("messages") or [])[-self.window_size :])
        return out

    def _estimate_tokens(self, api_messages: list[dict], task: dict) -> dict:
        model = self.model
        prompt_estimate = count_messages_tokens(api_messages, model)
        return {
            "model": model,
            "context_limit": self.context_limit,
            "prompt_estimate": prompt_estimate,
            "over_limit": prompt_estimate > self.context_limit,
            "cost_usd": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "stage": task.get("stage"),
            "paused": task.get("paused"),
        }

    def snapshot(self) -> dict:
        task = self.active_task()
        api = self._build_api_messages(task) if task else []
        tokens = self.last_tokens or (
            self._estimate_tokens(api, task) if task else {}
        )
        return {
            "role": self.role,
            "model": self.model,
            "context_limit": self.context_limit,
            "active_task_id": self.active_task_id,
            "tasks": self.list_tasks_summary(),
            "task": self._task_public(task) if task else None,
            "messages": list(task.get("messages") or []) if task else [],
            "tokens": tokens,
            "last_api_messages": list(self.last_api_messages or api),
            "usage_log": list(self.usage_log[-20:]),
        }

    def reply(self, user_message: str, *, as_system_nudge: bool = False) -> dict:
        task = self.active_task()
        if not task:
            raise ValueError("No active task — create one first")
        text = (user_message or "").strip()
        if not text:
            raise ValueError("Empty message")

        # System nudges are not shown as user bubbles — still sent to model as user role
        # but we store them tagged so UI can hide or show softly
        if as_system_nudge:
            # Don't append nudge to visible history as user; only assistant reply
            visible_user = None
        else:
            visible_user = {"role": "user", "content": text}
            task["messages"].append(visible_user)

        api_messages = self._build_api_messages(task)
        if as_system_nudge:
            api_messages = list(api_messages) + [
                {"role": "user", "content": text}
            ]

        tokens = self._estimate_tokens(api_messages, task)
        self.last_api_messages = api_messages
        self.last_tokens = tokens

        if tokens["over_limit"]:
            if visible_user:
                task["messages"].pop()
            self._save_tasks()
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
            if visible_user:
                task["messages"].pop()
            self._save_tasks()
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
            }
        )
        self.last_tokens = tokens
        self.usage_log.append(
            {
                "kind": "chat",
                "model": self.model,
                "task_id": task["task_id"],
                "stage": task["stage"],
                "paused": task["paused"],
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost,
            }
        )
        self._save_settings()
        task["messages"].append({"role": "assistant", "content": reply})
        # refresh summary lightly from last assistant if empty-ish
        if len(reply) > 40 and len(task.get("summary") or "") < 40:
            task["summary"] = reply[:500]
        self._save_tasks()
        snap = self.snapshot()
        snap["reply"] = reply
        return snap
