"""Per-turn LLM tracing. Best-effort: never raises into the chat loop.

Two artifacts per turn:
  - traces/summary.jsonl       one JSON object per line (cheap to grep)
  - traces/full/<turn_id>.json verbatim message list (replay/debug)
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRACES_DIR = Path(__file__).parent / "traces"
SUMMARY_FILE = TRACES_DIR / "summary.jsonl"
FULL_DIR = TRACES_DIR / "full"

_turns: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def start_turn(user_message: str) -> str:
    ts = _now_iso()
    # Sanitize timestamp for use in filenames (replace colons)
    safe_ts = ts.replace(":", "-")
    turn_id = f"{safe_ts}-{uuid.uuid4().hex[:6]}"
    with _lock:
        _turns[turn_id] = {
            "turn_id": turn_id,
            "timestamp": ts,
            "user_message_chars": len(user_message or ""),
            "model": None,
            "n_llm_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_ms": 0,
            "tool_calls": [],
            "subagent_calls": [],
            "final_text_chars": 0,
        }
    return turn_id


def last_turn_summary() -> dict | None:
    try:
        if not SUMMARY_FILE.exists():
            return None
        with SUMMARY_FILE.open("r", encoding="utf-8") as f:
            last = None
            for line in f:
                line = line.strip()
                if line:
                    last = line
            if last is None:
                return None
            return json.loads(last)
    except Exception:
        return None


def record_completion(turn_id: str, response: Any, latency_ms: float) -> None:
    try:
        with _lock:
            t = _turns.get(turn_id)
            if t is None:
                return
            t["n_llm_calls"] += 1
            t["latency_ms"] += float(latency_ms or 0)
            model = getattr(response, "model", None)
            if model:
                t["model"] = model
            usage = getattr(response, "usage", None)
            if usage is None:
                return
            p = int(getattr(usage, "prompt_tokens", 0) or 0)
            c = int(getattr(usage, "completion_tokens", 0) or 0)
            tot = int(getattr(usage, "total_tokens", p + c) or (p + c))
            t["prompt_tokens"] += p
            t["completion_tokens"] += c
            t["total_tokens"] += tot
    except Exception:
        return


def _digest_args(args: Any, max_len: int = 200) -> str:
    try:
        s = json.dumps(args, default=str, separators=(",", ":"))
    except Exception:
        s = str(args)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def record_tool_call(turn_id: str, name: str, args: Any,
                     result_chars: int, ms: float) -> None:
    try:
        with _lock:
            t = _turns.get(turn_id)
            if t is None:
                return
            t["tool_calls"].append({
                "name": name,
                "args_digest": _digest_args(args),
                "result_chars": int(result_chars),
                "ms": float(ms),
            })
    except Exception:
        return


def _ensure_dirs() -> None:
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    FULL_DIR.mkdir(parents=True, exist_ok=True)


def end_turn(turn_id: str, final_text: str, messages: list[dict]) -> None:
    try:
        with _lock:
            t = _turns.pop(turn_id, None)
        if t is None:
            return
        t["final_text_chars"] = len(final_text or "")

        _ensure_dirs()
        with SUMMARY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(t) + "\n")
        full_path = FULL_DIR / f"{turn_id}.json"
        full_path.write_text(
            json.dumps({"turn_id": turn_id, "messages": messages}, default=str, indent=2),
            encoding="utf-8",
        )
    except Exception:
        return


def attach_subagent(parent_turn_id: str, sub_summary: dict) -> None:
    """Called by subagent code to nest its summary under the parent turn."""
    try:
        with _lock:
            t = _turns.get(parent_turn_id)
            if t is None:
                return
            t["subagent_calls"].append(sub_summary)
    except Exception:
        return
