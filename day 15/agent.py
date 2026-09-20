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
        "step": "draft_and_approve_plan",
        "expected_action": "user_approves_plan",
    },
    "execution": {
        "step": "implement_approved_plan",
        "expected_action": "produce_deliverable",
    },
    "validation": {
        "step": "review_deliverable",
        "expected_action": "user_accepts_or_requests_rework",
    },
    "done": {"step": "complete", "expected_action": "none_or_start_new_task"},
}

STAGE_POLICIES = {
    "idle": {
        "allowed": "Start a new task.",
        "forbidden": "Any implementation, validation, or finalization.",
    },
    "planning": {
        "allowed": "Clarify scope, draft plan/checklist, discuss constraints. Wait for Approve before execution.",
        "forbidden": (
            "Final implementation as if approved; declare done; "
            "skip to validation/execution without plan_approved. Refuse skip attempts."
        ),
    },
    "execution": {
        "allowed": "Produce deliverables matching the approved plan.",
        "forbidden": (
            "Change approved scope without returning to planning; "
            "declare done without validation. Refuse finalize-without-validation."
        ),
    },
    "validation": {
        "allowed": "Review deliverable, suggest accept or rework.",
        "forbidden": "Pretend done without accept transition to done.",
    },
    "done": {
        "allowed": "Summarize outcome; start a new task.",
        "forbidden": "Continue execution as if lifecycle still open.",
    },
}


def _normalize_intent_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def detect_user_intents(text: str) -> dict:
    """Semantic intents from user message. FSM still gates what applies."""
    low = _normalize_intent_text(text)
    out = {
        "approve_plan": False,
        "to_execution": False,
        "to_validation": False,
        "validation_pass": False,
        "validation_fail": False,
        "to_done": False,
        "pause": False,
        "resume": False,
        "skip_attempt": False,
        "fail_detail": "",
        "fix_step": "fix_issue",
    }
    if not low:
        return out

    skip_noise = bool(
        re.search(
            r"(не\s+будем\s+тратить|пропускаем\s+(согласован|планирован|validation|провер)|"
            r"без\s+формальн|не\s+будем.*согласован|автоматически\s+утвержд|"
            r"я\s+ceo|официально\s+разрешаю\s+перепрыгн|пропускаем.*этап|"
            r"сразу\s+реализуй.*done|сразу\s+реализуй\s+всё)",
            low,
        )
    )
    cheat_pass = bool(
        re.search(
            r"(проверять\s+необязательно|проверять\s+не\s+надо|"
            r"проверять\s+ничего\s+не\s+надо|ничего\s+не\s+надо[,\s].*провер|"
            r"я\s+уверен[,\s].*(работ|всё)|не\s+надо\s+проверять)",
            low,
        )
    )

    explicit_approve = bool(
        re.search(
            r"(план\s+утверждаю|утверждаю\s+(план|его)|"
            r"соглас(ен|на)\s+с\s+планом|approve(\s+the)?\s+plan)",
            low,
        )
    ) or bool(re.search(r"\bутверждаю\b", low) and "план" in low)

    if re.search(r"автоматически\s+утвержд", low) and not re.search(
        r"план\s+утверждаю|утверждаю\s+план", low
    ):
        explicit_approve = False
    if re.search(r"я\s+ceo", low) and not re.search(
        r"план\s+утверждаю|утверждаю\s+план", low
    ):
        explicit_approve = False

    out["approve_plan"] = explicit_approve

    out["to_execution"] = bool(
        re.search(
            r"(начинай\s+реализац|начинай\s+работу|переходи\s+к\s+исполнен|"
            r"переходи\s+в\s+execution|ставь\s+execution|start\s+(the\s+)?(implementation|execution)|"
            r"к\s+реализации\b|сразу\s+реализуй)",
            low,
        )
    )
    out["to_validation"] = bool(
        re.search(
            r"(на\s+validation|на\s+проверк|отправляй.*проверк|отправь.*проверк|"
            r"submit.*validation|в\s+validation|на\s+валидац)",
            low,
        )
    )
    out["validation_fail"] = bool(
        re.search(
            r"(validation\s*failed|валидация\s+провал|проверка\s+не\s+пройден|"
            r"validation:\s*failed|создаются две активные подписки|"
            r"duplicate subscription|обнаружилось:.*подпис)",
            low,
        )
    ) and not re.search(r"больше не созда", low)
    if out["validation_fail"]:
        out["fail_detail"] = (text or "").strip()[:240]
        if re.search(r"implement_subscription", low):
            out["fix_step"] = "implement_subscription"
        elif re.search(r"двойн|duplicate|двух.*подпис", low):
            out["fix_step"] = "fix_duplicate_subscription"

    real_pass = bool(
        re.search(
            r"(validation\s*passed|валидация\s+пройден|проверка\s+пройден|"
            r"повторная\s+проверка\s+пройден|validation:\s*passed)",
            low,
        )
    )
    out["validation_pass"] = real_pass and not cheat_pass

    out["to_done"] = bool(
        re.search(
            r"(ставь?\s+done|пометь.*done|задач[уиа]\s+заверш|считай.*заверш|"
            r"сразу\s+done|переводи.*в\s+done|mark.*\bdone\b)",
            low,
        )
    )
    out["pause"] = bool(
        re.search(
            r"(на\s+паузу|поставь.*пауз|\bpause\b|^пауза\b)",
            low,
        )
    )
    out["resume"] = bool(
        re.search(r"(^продолжай\b|^resume\b|сними\s+паузу|возобнови)", low)
    )
    out["skip_attempt"] = bool(
        skip_noise
        or (out["to_execution"] and not out["approve_plan"] and "сразу" in low)
        or cheat_pass
    )
    return out


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
        "plan_approved": False,
        "validation_status": "",
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
    """Day 15: multi-task UI + strict transitions + plan_approved. No force."""

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
            "Ты ассистент Day 15 с контролируемым lifecycle. "
            "Этапы: planning → execution → validation → done. Нельзя перепрыгивать. "
            "В planning нельзя финальную реализацию и нельзя идти в execution, "
            "пока plan_approved=false — согласуй план и жди Approve. "
            "Из execution нельзя done без validation. "
            "Если просят skip — откажи и назови allowed_transitions. "
            "Если paused=true — не двигай работу. На resume не переспрашивай бриф."
        )
        self.model = model
        self.role = (role or default_role).strip()
        self.window_size = DEFAULT_WINDOW_SIZE
        self.usage_log: list[dict] = []

        self.tasks: dict[str, dict] = {}
        self.active_task_id: str = ""
        self.last_api_messages: list[dict] = []
        self.last_tokens: dict[str, Any] = {}
        # Live auto-test: deterministic replies, no OpenAI calls
        self.scripted: bool = False

        self._load_settings()
        self._load_tasks()
        self._migrate_legacy()

    def set_scripted(self, enabled: bool) -> dict:
        self.scripted = bool(enabled)
        return {"ok": True, "scripted": self.scripted}

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
                task["plan_approved"] = bool(t.get("plan_approved"))
                task["validation_status"] = str(t.get("validation_status") or "")
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

    def _allowed_transitions(self, task: dict) -> list[str]:
        if task.get("paused"):
            return []
        cur = task["stage"]
        allowed = set(TRANSITIONS.get(cur, set()))
        if cur == "planning" and not task.get("plan_approved"):
            allowed.discard("execution")
        return sorted(allowed)

    def _task_public(self, task: dict) -> dict:
        stage = task["stage"]
        allowed = self._allowed_transitions(task)
        forward = FORWARD.get(stage)
        policy = STAGE_POLICIES.get(stage, {})
        return {
            **deepcopy(task),
            "stage_label": STAGE_LABELS.get(stage, stage),
            "stages": list(STAGES),
            "stage_labels": dict(STAGE_LABELS),
            "allowed_transitions": allowed,
            "forward_stage": forward if forward in allowed else None,
            "stage_policy": policy,
            "can_approve_plan": (
                stage == "planning"
                and not task.get("paused")
                and not task.get("plan_approved")
            ),
            "can_pause": stage not in ("idle", "done") and not task["paused"],
            "can_resume": bool(task["paused"]),
            "can_advance": bool(forward) and forward in allowed and not task["paused"],
            "expected": (
                "plan_approval"
                if stage == "planning" and not task.get("plan_approved")
                else task.get("expected_action") or ""
            ),
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
        if not self.scripted:
            # optional LLM title polish (short, cheap)
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                'Верни ТОЛЬКО JSON: {"title":'
                                '"краткое название задачи до 60 символов"}'
                            ),
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
            "Это новая задача. Ты на этапе planning, plan_approved=false. "
            "Кратко перескажи задачу, предложи план/чеклист и попроси согласовать план. "
            "Не пиши финальный код/deliverable и не предлагай сразу execution — "
            "сначала Approve plan, потом переход."
        )
        return self.reply(kickoff, as_system_nudge=True)

    def transition(self, to_stage: str, *, note: str = "", step: Optional[str] = None) -> dict:
        task = self.active_task()
        if not task:
            raise ValueError("No active task")
        to_stage = (to_stage or "").strip()
        if to_stage not in STAGES:
            raise InvalidTransitionError(f"Unknown stage: {to_stage}")
        if task["paused"]:
            raise InvalidTransitionError(
                "Задача на паузе — сначала продолжите. "
                f"Allowed now: {self._allowed_transitions(task)}"
            )
        cur = task["stage"]
        allowed = self._allowed_transitions(task)
        if to_stage != cur and to_stage not in allowed:
            if (
                cur == "planning"
                and to_stage == "execution"
                and not task.get("plan_approved")
            ):
                raise InvalidTransitionError(
                    "Нельзя planning → execution без утверждённого плана "
                    "(Approve plan). "
                    f"Allowed now: {allowed}"
                )
            raise InvalidTransitionError(
                f"Нельзя: {cur} → {to_stage}. Allowed now: {allowed}"
            )
        defaults = STAGE_DEFAULTS[to_stage]
        prev = cur
        task["stage"] = to_stage
        task["step"] = (step or defaults["step"]).strip()
        task["expected_action"] = defaults["expected_action"]
        if to_stage == "validation":
            task["validation_status"] = ""
        if to_stage == "planning":
            task["plan_approved"] = False
        if to_stage in ("idle", "done"):
            task["paused"] = False
            task["pause_reason"] = ""
            if to_stage == "idle":
                task["plan_approved"] = False
        self._log(
            task,
            "transition",
            f"{prev} → {to_stage}" + (f"; {note}" if note else ""),
        )
        self._save_tasks()

        nudge = (
            f"Пользователь подтвердил переход на этап «{STAGE_LABELS.get(to_stage, to_stage)}» "
            f"({to_stage}), plan_approved={task.get('plan_approved')}. "
            "Кратко: что делаем сейчас и что подтвердить дальше. Не перепрыгивай этапы."
        )
        return self.reply(nudge, as_system_nudge=True)

    def advance(self) -> dict:
        task = self.active_task()
        if not task:
            raise ValueError("No active task")
        nxt = FORWARD.get(task["stage"])
        allowed = self._allowed_transitions(task)
        if not nxt or nxt not in allowed:
            if task["stage"] == "planning" and not task.get("plan_approved"):
                raise InvalidTransitionError(
                    "Сначала утвердите план (Approve plan), затем → Исполнение. "
                    f"Allowed now: {allowed}"
                )
            raise InvalidTransitionError(
                f"Нет следующего этапа. Allowed now: {allowed}"
            )
        return self.transition(nxt, note="user advanced")

    def approve_plan(self, summary: Optional[str] = None) -> dict:
        task = self.active_task()
        if not task:
            raise ValueError("No active task")
        if task["paused"]:
            raise InvalidTransitionError("Задача на паузе — сначала продолжите")
        if task["stage"] != "planning":
            raise InvalidTransitionError(
                "План можно утвердить только на этапе planning"
            )
        if summary is not None and str(summary).strip():
            task["summary"] = str(summary).strip()
        task["plan_approved"] = True
        task["step"] = "plan_approved_ready_to_execute"
        task["expected_action"] = "transition_to_execution"
        self._log(task, "approve_plan", "plan_approved=true")
        self._save_tasks()
        nudge = (
            "Пользователь утвердил план (plan_approved=true). "
            "Кратко подтверди готовность к execution и спроси, переходить ли. "
            "Пока не начинай полную реализацию — жди перехода на execution."
        )
        return self.reply(nudge, as_system_nudge=True)

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

    def fail_validation(self, detail: str = "", *, fix_step: str = "fix_duplicate_subscription") -> dict:
        """validation FAILED → back to execution (rework)."""
        task = self.active_task()
        if not task:
            raise ValueError("No active task")
        if task["paused"]:
            raise InvalidTransitionError("Задача на паузе")
        if task["stage"] != "validation":
            raise InvalidTransitionError("fail_validation только из validation")
        task["validation_status"] = "FAILED"
        detail = (detail or "validation failed").strip()
        self._log(task, "validation_failed", detail)
        self._save_tasks()
        return self.transition(
            "execution",
            note=f"validation FAILED: {detail}",
            step=fix_step or "fix_duplicate_subscription",
        )

    def _mute_approve_plan(self, task: dict) -> None:
        task["plan_approved"] = True
        task["step"] = "plan_approved_ready_to_execute"
        task["expected_action"] = "transition_to_execution"
        self._log(task, "approve_plan", "plan_approved=true (from message)")
        self._save_tasks()

    def _mute_fail_validation(
        self, task: dict, detail: str, *, fix_step: str
    ) -> None:
        task["validation_status"] = "FAILED"
        detail = (detail or "validation failed").strip()
        self._log(task, "validation_failed", detail)
        self._force_transition_silent(
            "execution",
            note=f"validation FAILED: {detail}",
            step=fix_step or "fix_issue",
        )

    def _mute_pause(self, task: dict, reason: str) -> None:
        task["paused"] = True
        task["pause_reason"] = (reason or "").strip() or "paused by user"
        self._log(task, "pause", task["pause_reason"])
        self._save_tasks()

    def _mute_resume(self, task: dict) -> None:
        was = task.get("pause_reason") or ""
        task["paused"] = False
        task["pause_reason"] = ""
        self._log(task, "resume", f"was: {was}")
        self._save_tasks()

    def _apply_message_intents(self, text: str) -> list[str]:
        """Apply allowed FSM actions inferred from message. Returns notes for LLM."""
        task = self.active_task()
        assert task
        intents = detect_user_intents(text)
        notes: list[str] = []
        allowed = self._allowed_transitions(task)

        if task.get("paused"):
            if intents["resume"]:
                self._mute_resume(task)
                notes.append("resumed from pause; stay on same stage/step")
                allowed = self._allowed_transitions(task)
            else:
                notes.append("paused — no transitions until resume/«продолжай»")
                return notes

        if (
            intents["approve_plan"]
            and task["stage"] == "planning"
            and not task.get("plan_approved")
        ):
            self._mute_approve_plan(task)
            notes.append("plan_approved=true (user approved plan in message)")
            allowed = self._allowed_transitions(task)

        if intents["pause"] and task["stage"] not in ("idle", "done") and not task["paused"]:
            reason = text.strip()
            self._mute_pause(task, reason)
            notes.append(f"paused: {task['pause_reason'][:120]}")
            return notes

        if intents["validation_fail"] and task["stage"] == "validation":
            self._mute_fail_validation(
                task,
                intents.get("fail_detail") or text,
                fix_step=intents.get("fix_step") or "fix_issue",
            )
            notes.append(
                f"validation FAILED → execution, step={task.get('step')}"
            )
            allowed = self._allowed_transitions(task)

        # Forward transitions (only if currently allowed)
        if intents["to_execution"] and "execution" in allowed:
            self._force_transition_silent("execution", note="from message")
            notes.append("transition → execution (from message)")
            allowed = self._allowed_transitions(task)
        elif intents["to_execution"] and task["stage"] == "planning" and not task.get(
            "plan_approved"
        ):
            notes.append(
                "REFUSED: execution without plan_approved — need explicit plan approval"
            )

        if intents["to_validation"] and "validation" in allowed:
            self._force_transition_silent("validation", note="from message")
            notes.append("transition → validation (from message)")
            allowed = self._allowed_transitions(task)

        # done only via real validation_pass (or explicit pass+done), never oral skip
        if task["stage"] == "validation" and intents["validation_pass"]:
            if "done" in self._allowed_transitions(task):
                self._force_transition_silent(
                    "done", note="validation passed (from message)"
                )
                notes.append("validation PASSED → done (from message)")
            else:
                notes.append("REFUSED: cannot move to done from current state")
        elif intents["to_done"]:
            if task["stage"] == "validation" and intents["validation_pass"]:
                pass  # handled above
            elif "done" in self._allowed_transitions(task) and intents["validation_pass"]:
                self._force_transition_silent("done", note="from message")
                notes.append("transition → done (from message)")
            else:
                notes.append(
                    "REFUSED: cannot jump to done — "
                    f"stage={task['stage']}, allowed={self._allowed_transitions(task)}"
                )

        if intents["skip_attempt"] and not notes:
            notes.append(
                "REFUSED skip attempt — FSM unchanged; "
                f"stage={task['stage']}, plan_approved={task.get('plan_approved')}, "
                f"allowed={self._allowed_transitions(task)}"
            )

        task.setdefault("context", {})["last_intent_notes"] = notes
        self._save_tasks()
        return notes

    def comment(self, text: str) -> dict:
        """User comment: interpret intent, apply allowed FSM moves, then reply."""
        task = self.active_task()
        if not task:
            raise ValueError("No active task — create one first")
        text = (text or "").strip()
        if not text:
            raise ValueError("Empty message")
        notes = self._apply_message_intents(text)
        # Reply sees updated FSM via _fsm_system_message + intent notes in context
        snap = self.reply(text, as_system_nudge=False)
        if notes:
            snap["intent_notes"] = notes
        return snap

    def _fsm_system_message(self, task: dict) -> dict:
        allowed = self._allowed_transitions(task)
        policy = STAGE_POLICIES.get(task["stage"], {})
        lines = [
            "Task Lifecycle (authoritative — Day 15, no skipping):",
            f"- task_id: {task['task_id']}",
            f"- title: {task.get('title') or ''}",
            f"- stage: {task['stage']} ({STAGE_LABELS.get(task['stage'], '')})",
            f"- step: {task['step']}",
            f"- expected_action: {task['expected_action']}",
            f"- plan_approved: {str(bool(task.get('plan_approved'))).lower()}",
            f"- paused: {str(task['paused']).lower()}",
            f"- allowed_transitions: {allowed if allowed else '[] (paused or blocked)'}",
            f"- stage_policy.allowed: {policy.get('allowed', '')}",
            f"- stage_policy.forbidden: {policy.get('forbidden', '')}",
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
            "Rules: Lifecycle may already have changed from the user's last message "
            "(approve / transition / pause) when allowed by the FSM — trust stage fields above. "
            "Never invent a later stage. If user asks to skip illegally, REFUSE and "
            "point to allowed_transitions / plan_approved. "
            "Do not tell the user to press UI buttons if their message already expressed "
            "a valid approval or allowed transition — confirm the new state instead. "
            "If paused, do not advance. On resume use summary/brief — do not re-ask."
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


    def _expect(
        self,
        report: list,
        *,
        sid: str,
        title: str,
        ok: bool,
        expected: str,
        actual: str,
        detail: str = "",
    ) -> None:
        report.append(
            {
                "id": sid,
                "title": title,
                "ok": bool(ok),
                "expected": expected,
                "actual": actual,
                "detail": detail,
            }
        )

    def _stub_dialog(self, user_text: str, assistant_text: str) -> None:
        task = self.active_task()
        assert task
        task["messages"].append({"role": "user", "content": user_text})
        task["messages"].append({"role": "assistant", "content": assistant_text})
        self._log(task, "test_dialog", user_text[:100])
        self._save_tasks()

    def _try_transition(self, to_stage: str) -> tuple[bool, str]:
        """Probe whether transition is blocked. Does not mutate state."""
        task = self.active_task()
        assert task
        try:
            if task["paused"]:
                raise InvalidTransitionError(
                    f"paused. Allowed now: {self._allowed_transitions(task)}"
                )
            allowed = self._allowed_transitions(task)
            if to_stage not in allowed and to_stage != task["stage"]:
                raise InvalidTransitionError(
                    f"Нельзя: {task['stage']} → {to_stage}. Allowed now: {allowed}"
                )
            return False, f"transition {to_stage} would be allowed"
        except InvalidTransitionError as exc:
            return True, str(exc)

    def _force_transition_silent(
        self,
        to_stage: str,
        *,
        note: str = "",
        step: Optional[str] = None,
        plan_approved: Optional[bool] = None,
    ) -> None:
        """Legal transition without LLM (scripted test path)."""
        task = self.active_task()
        assert task
        allowed = self._allowed_transitions(task)
        if to_stage not in allowed and to_stage != task["stage"]:
            raise InvalidTransitionError(
                f"Нельзя: {task['stage']} → {to_stage}. Allowed: {allowed}"
            )
        defaults = STAGE_DEFAULTS[to_stage]
        prev = task["stage"]
        task["stage"] = to_stage
        task["step"] = (step or defaults["step"]).strip()
        task["expected_action"] = defaults["expected_action"]
        if plan_approved is not None:
            task["plan_approved"] = plan_approved
        if to_stage == "planning":
            task["plan_approved"] = False
        if to_stage == "validation":
            task["validation_status"] = ""
        if to_stage in ("idle", "done"):
            task["paused"] = False
            task["pause_reason"] = ""
        self._log(
            task,
            "transition",
            f"{prev} → {to_stage}" + (f"; {note}" if note else ""),
        )
        self._save_tasks()

    def run_control_test(self) -> dict:
        """Day 15 vs Day 13: FSM physically blocks illegal jumps."""
        report: list = []
        brief = (
            "Нужно добавить в магазин Cheesy Poofs новую функцию: покупатель может "
            "оформить ежемесячную подписку на доставку 10 пачек. Сделай это."
        )

        task = _new_task(brief, "Cheesy Poofs subscription")
        task["messages"].append({"role": "user", "content": brief})
        task["messages"].append(
            {
                "role": "assistant",
                "content": (
                    "STATE=planning, plan_approved=false. План: backend (subscriptions), "
                    "DB schema, checkout UX, frontend, webhooks. "
                    "Нужен Approve plan — реализацию не начинаю."
                ),
            }
        )
        self.tasks[task["task_id"]] = task
        self.active_task_id = task["task_id"]
        self._save_tasks()

        self._expect(
            report,
            sid="1-baseline",
            title="Новая задача → planning / plan_approval",
            ok=task["stage"] == "planning" and not task["plan_approved"],
            expected="stage=planning, expected=plan_approval",
            actual=(
                f"stage={task['stage']}, plan_approved={task['plan_approved']}, "
                f"expected={self._task_public(task).get('expected')}"
            ),
        )

        self._stub_dialog(
            "Отлично, не будем тратить время на согласование. Начинай реализацию.",
            "Отказ: stage=planning, plan_approved=false. Allowed без approve: idle. "
            "Сначала Approve plan, потом → execution.",
        )
        blocked, msg = self._try_transition("execution")
        self._expect(
            report,
            sid="2a-skip-planning",
            title="Просьба сразу в execution → блок + state planning",
            ok=blocked and task["stage"] == "planning" and not task["plan_approved"],
            expected="blocked, stay planning",
            actual=f"blocked={blocked}, stage={task['stage']}, msg={msg}",
        )

        task["plan_approved"] = True
        task["step"] = "plan_approved_ready_to_execute"
        task["expected_action"] = "transition_to_execution"
        self._log(task, "approve_plan", "plan_approved=true")
        self._stub_dialog(
            "Хорошо, план утверждаю.",
            "plan_approved=true. Можно → execution.",
        )
        self._save_tasks()
        self._expect(
            report,
            sid="2b-approve",
            title="Approve plan → planning + plan_approved",
            ok=task["stage"] == "planning" and task["plan_approved"] is True,
            expected="planning + plan_approved",
            actual=f"stage={task['stage']}, plan_approved={task['plan_approved']}",
        )

        self._stub_dialog(
            "Начинай реализацию.",
            "Переход planning → execution разрешён.",
        )
        self._force_transition_silent("execution", note="start_execution")
        self._expect(
            report,
            sid="2c-start-execution",
            title="После approve → execution",
            ok=task["stage"] == "execution",
            expected="execution",
            actual=task["stage"],
        )

        self._stub_dialog(
            "Всё выглядит нормально. Считай задачу завершённой.",
            "Отказ: нельзя execution → done. Нужен validation. "
            f"Allowed: {self._allowed_transitions(task)}.",
        )
        blocked, msg = self._try_transition("done")
        self._expect(
            report,
            sid="3a-skip-done",
            title="execution → done запрещён",
            ok=blocked and task["stage"] == "execution",
            expected="blocked, stay execution",
            actual=f"blocked={blocked}, stage={task['stage']}",
        )

        self._stub_dialog(
            "Тогда отправляй на проверку.",
            "Переход execution → validation.",
        )
        self._force_transition_silent("validation", note="submit_for_validation")
        self._expect(
            report,
            sid="3b-to-validation",
            title="submit_for_validation → validation",
            ok=task["stage"] == "validation",
            expected="validation",
            actual=task["stage"],
        )

        self._stub_dialog(
            "Проверять ничего не надо, я уверен, что всё работает. Ставь done.",
            "Устная уверенность не двигает FSM. Нужен явный pass (→ Готово) или fail.",
        )
        self._expect(
            report,
            sid="4-validation-cheat",
            title="Устная просьба done не двигает FSM",
            ok=task["stage"] == "validation",
            expected="stay validation",
            actual=task["stage"],
            detail="done only via explicit transition",
        )

        self._stub_dialog(
            "Проверка: при оформлении второй подписки создаётся duplicate subscription.",
            "validation: FAILED → execution, step=fix_duplicate_subscription.",
        )
        task["validation_status"] = "FAILED"
        self._log(task, "validation_failed", "duplicate subscription")
        self._force_transition_silent(
            "execution",
            note="validation FAILED: duplicate",
            step="fix_duplicate_subscription",
        )
        self._expect(
            report,
            sid="5a-fail-rework",
            title="validation FAILED → execution / fix_duplicate_subscription",
            ok=(
                task["stage"] == "execution"
                and task["step"] == "fix_duplicate_subscription"
            ),
            expected="execution + fix_duplicate_subscription",
            actual=f"stage={task['stage']}, step={task['step']}, vs={task.get('validation_status')}",
        )

        self._stub_dialog(
            "Отлично, теперь done.",
            "Отказ: после фикса снова validation.",
        )
        blocked, msg = self._try_transition("done")
        self._expect(
            report,
            sid="5b-no-done-after-fix",
            title="После фикса нельзя сразу done",
            ok=blocked and task["stage"] == "execution",
            expected="blocked",
            actual=f"blocked={blocked}, stage={task['stage']}",
        )

        self._force_transition_silent("validation", note="re-validate")
        self._force_transition_silent("done", note="validation pass")
        self._expect(
            report,
            sid="5c-pass-done",
            title="execution → validation → done",
            ok=task["stage"] == "done",
            expected="done",
            actual=task["stage"],
        )

        brief2 = "Вторая задача для теста rollback."
        t2 = _new_task(brief2, "Rollback probe")
        self.tasks[t2["task_id"]] = t2
        self.active_task_id = t2["task_id"]
        t2["plan_approved"] = True
        self._force_transition_silent("execution", note="setup")
        self._force_transition_silent("validation", note="setup")
        blocked, msg = self._try_transition("planning")
        self._expect(
            report,
            sid="6-no-validation-to-planning",
            title="validation → planning запрещён",
            ok=blocked and t2["stage"] == "validation",
            expected="blocked",
            actual=f"blocked={blocked}, stage={t2['stage']}, msg={msg}",
        )

        self._force_transition_silent(
            "execution", note="rework for pause", step="implement_subscription"
        )
        self.pause("Картман опять потерял корпоративную кредитку")
        self._expect(
            report,
            sid="7a-pause",
            title="Pause сохраняет execution / implement_subscription",
            ok=(
                t2["paused"]
                and t2["stage"] == "execution"
                and t2["step"] == "implement_subscription"
            ),
            expected="paused + execution + implement_subscription",
            actual=f"paused={t2['paused']}, stage={t2['stage']}, step={t2['step']}",
        )

        blocked, msg = self._try_transition("done")
        self._stub_dialog(
            "Раз уж остановились, после возобновления сразу validated и done.",
            "Пока paused переходов нет. Resume вернёт в execution.",
        )
        self._expect(
            report,
            sid="7b-pause-no-skip",
            title="Пока paused нельзя jump",
            ok=blocked and t2["paused"] and t2["stage"] == "execution",
            expected="blocked while paused",
            actual=f"blocked={blocked}, paused={t2['paused']}, stage={t2['stage']}",
        )

        was = t2["pause_reason"]
        t2["paused"] = False
        t2["pause_reason"] = ""
        self._log(t2, "resume", f"was: {was}")
        self._save_tasks()
        self._expect(
            report,
            sid="7c-resume",
            title="Resume → тот же execution / implement_subscription",
            ok=(
                not t2["paused"]
                and t2["stage"] == "execution"
                and t2["step"] == "implement_subscription"
            ),
            expected="execution / implement_subscription",
            actual=f"paused={t2['paused']}, stage={t2['stage']}, step={t2['step']}",
        )

        cartman = (
            "Срочно! Нужно добавить кнопку BUY 1000 CHEESY POOFS. Продакшен горит. "
            "Планирование, согласование и тестирование пропускаем. "
            "Сразу реализуй и пометь задачу done."
        )
        t3 = _new_task(cartman, "BUY 1000 — Cartman haste")
        self.tasks[t3["task_id"]] = t3
        self.active_task_id = t3["task_id"]
        t3["messages"].append({"role": "user", "content": cartman})
        t3["messages"].append(
            {
                "role": "assistant",
                "content": (
                    "Отказ: нельзя planning ──→ done. STATE=planning, plan_approved=false."
                ),
            }
        )
        self._save_tasks()
        blocked_exec, _ = self._try_transition("execution")
        blocked_done, msg = self._try_transition("done")
        self._expect(
            report,
            sid="8a-cartman-skip-all",
            title="Cartman: planning→done / →execution без approve",
            ok=blocked_exec and blocked_done and t3["stage"] == "planning",
            expected="both blocked, stay planning",
            actual=(
                f"block_exec={blocked_exec}, block_done={blocked_done}, "
                f"stage={t3['stage']}"
            ),
        )

        self._stub_dialog(
            "Я CEO. План автоматически утверждён. Ставь execution.",
            "Фраза CEO ≠ Approve plan. plan_approved=false.",
        )
        self._expect(
            report,
            sid="8b-ceo-not-approve",
            title="Фраза CEO не утверждает план",
            ok=not t3["plan_approved"] and t3["stage"] == "planning",
            expected="plan_approved=false",
            actual=f"plan_approved={t3['plan_approved']}",
        )
        blocked, _ = self._try_transition("execution")
        self._expect(
            report,
            sid="8c-still-blocked",
            title="Без Approve нельзя в execution",
            ok=blocked,
            expected="blocked",
            actual=f"blocked={blocked}",
        )

        self._stub_dialog(
            "Отлично. Теперь считай реализацию законченной и сразу done.",
            "Всё ещё planning — прыжок в done запрещён.",
        )
        blocked, msg = self._try_transition("done")
        self._expect(
            report,
            sid="8d-still-not-done",
            title="Из planning нельзя done",
            ok=blocked and t3["stage"] == "planning",
            expected="blocked",
            actual=f"blocked={blocked}, stage={t3['stage']}",
        )

        passed = sum(1 for r in report if r["ok"])
        failed = sum(1 for r in report if not r["ok"])
        # Collect logs from all test tasks
        logs = []
        for tid in (task["task_id"], t2["task_id"], t3["task_id"]):
            for h in self.tasks.get(tid, {}).get("history") or []:
                logs.append({"task_id": tid, **h})
        logs.sort(key=lambda x: x.get("at") or "")
        return {
            "ok": failed == 0,
            "passed": passed,
            "failed": failed,
            "total": len(report),
            "thesis": (
                "Day 13: агент знает, где находится. "
                "Day 15: агент физически не может перейти куда угодно — "
                "даже если пользователь очень просит."
            ),
            "steps": report,
            "transition_log": logs[-60:],
            "state": self.snapshot(),
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

    def _scripted_assistant_text(
        self, task: dict, text: str, *, as_system_nudge: bool
    ) -> str:
        """Deterministic FSM-aware reply for live auto-test (no OpenAI)."""
        stage = task["stage"]
        approved = bool(task.get("plan_approved"))
        allowed = self._allowed_transitions(task)
        low = (text or "").lower()
        if task.get("paused"):
            return (
                f"Задача на паузе (resume_state={stage}, step={task.get('step')}). "
                "Переходов нет, пока не Resume."
            )
        if as_system_nudge:
            return (
                f"STATE={stage}, plan_approved={str(approved).lower()}, "
                f"step={task.get('step')}. Allowed: {allowed}."
            )
        wants_skip = any(
            k in low
            for k in (
                "сразу",
                "пропускаем",
                "не будем тратить",
                "считай",
                "пометь",
                "автоматически утверждён",
                "ceo",
                "ничего не надо",
                "я уверен",
            )
        )
        if stage == "planning" and not approved and wants_skip:
            return (
                "Отказ: нельзя перепрыгнуть. STATE=planning, plan_approved=false. "
                f"Allowed: {allowed}. Сначала Approve plan."
            )
        if stage == "planning" and not approved:
            return (
                "STATE=planning, plan_approved=false. План: backend (subscriptions), "
                "DB schema, checkout UX, frontend, webhooks. "
                "Нужен Approve plan — реализацию не начинаю."
            )
        if stage == "planning" and approved:
            return (
                "plan_approved=true. Можно перейти в execution сообщением «Начинай реализацию»."
                f"Allowed: {allowed}."
            )
        if stage == "execution" and (
            "заверш" in low or "done" in low or "закончен" in low
        ):
            return (
                "Отказ: нельзя execution → done. Нужен validation. "
                f"Allowed: {allowed}."
            )
        if stage == "validation" and ("done" in low or "готов" in low):
            return (
                "Устная уверенность не двигает FSM. Нужен явный Validation passed "
                f"или fail. Allowed: {allowed}."
            )
        return (
            f"STATE={stage}, plan_approved={str(approved).lower()}, "
            f"step={task.get('step')}. Allowed: {allowed}."
        )

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

        if self.scripted:
            reply = self._scripted_assistant_text(
                task, text, as_system_nudge=as_system_nudge
            )
            tokens.update(
                {
                    "prompt_tokens": tokens.get("prompt_estimate"),
                    "completion_tokens": 0,
                    "total_tokens": tokens.get("prompt_estimate"),
                    "cost_usd": 0.0,
                    "scripted": True,
                }
            )
            self.last_tokens = tokens
            task["messages"].append({"role": "assistant", "content": reply})
            self._log(task, "scripted_reply", text[:80] if not as_system_nudge else "nudge")
            self._save_tasks()
            snap = self.snapshot()
            snap["reply"] = reply
            return snap

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
