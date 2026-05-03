import json
from pathlib import Path

import tracing


def test_start_turn_returns_unique_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "TRACES_DIR", tmp_path)
    monkeypatch.setattr(tracing, "SUMMARY_FILE", tmp_path / "summary.jsonl")
    monkeypatch.setattr(tracing, "FULL_DIR", tmp_path / "full")

    a = tracing.start_turn("hello")
    b = tracing.start_turn("hi")

    assert a != b
    assert isinstance(a, str) and len(a) > 0


def test_last_turn_summary_returns_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "TRACES_DIR", tmp_path)
    monkeypatch.setattr(tracing, "SUMMARY_FILE", tmp_path / "summary.jsonl")
    monkeypatch.setattr(tracing, "FULL_DIR", tmp_path / "full")
    assert tracing.last_turn_summary() is None


class _FakeUsage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c
        self.total_tokens = p + c


class _FakeResponse:
    def __init__(self, model, p, c):
        self.model = model
        self.usage = _FakeUsage(p, c)


def test_record_completion_accumulates(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "TRACES_DIR", tmp_path)
    monkeypatch.setattr(tracing, "SUMMARY_FILE", tmp_path / "summary.jsonl")
    monkeypatch.setattr(tracing, "FULL_DIR", tmp_path / "full")

    tid = tracing.start_turn("hi")
    tracing.record_completion(tid, _FakeResponse("anthropic/sonnet", 100, 50), 1234.0)
    tracing.record_completion(tid, _FakeResponse("anthropic/sonnet", 80, 40), 678.0)

    snap = tracing._turns[tid]
    assert snap["model"] == "anthropic/sonnet"
    assert snap["n_llm_calls"] == 2
    assert snap["prompt_tokens"] == 180
    assert snap["completion_tokens"] == 90
    assert snap["total_tokens"] == 270
    assert snap["latency_ms"] == 1234 + 678


def test_record_tool_call_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "TRACES_DIR", tmp_path)
    monkeypatch.setattr(tracing, "SUMMARY_FILE", tmp_path / "summary.jsonl")
    monkeypatch.setattr(tracing, "FULL_DIR", tmp_path / "full")

    tid = tracing.start_turn("hi")
    tracing.record_tool_call(tid, "read_state", {"foo": "bar"}, 612, 4.0)
    tracing.record_tool_call(tid, "update_plan", {"slots": [1, 2]}, 41, 12.0)

    calls = tracing._turns[tid]["tool_calls"]
    assert [c["name"] for c in calls] == ["read_state", "update_plan"]
    assert calls[0]["result_chars"] == 612
    assert calls[1]["ms"] == 12.0
    # args_digest is stringy and bounded
    assert isinstance(calls[0]["args_digest"], str)
    assert len(calls[0]["args_digest"]) <= 200


def test_record_completion_handles_missing_usage(tmp_path, monkeypatch):
    """LiteLLM may not always populate usage. Tracing must not crash."""
    monkeypatch.setattr(tracing, "TRACES_DIR", tmp_path)
    monkeypatch.setattr(tracing, "SUMMARY_FILE", tmp_path / "summary.jsonl")
    monkeypatch.setattr(tracing, "FULL_DIR", tmp_path / "full")

    class _NoUsage:
        model = "x"
        usage = None

    tid = tracing.start_turn("hi")
    tracing.record_completion(tid, _NoUsage(), 100.0)  # must not raise

    snap = tracing._turns[tid]
    assert snap["n_llm_calls"] == 1
    assert snap["prompt_tokens"] == 0


def test_end_turn_writes_summary_and_full(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "TRACES_DIR", tmp_path)
    monkeypatch.setattr(tracing, "SUMMARY_FILE", tmp_path / "summary.jsonl")
    monkeypatch.setattr(tracing, "FULL_DIR", tmp_path / "full")

    tid = tracing.start_turn("hi")
    tracing.record_completion(tid, _FakeResponse("m", 10, 5), 50.0)
    tracing.record_tool_call(tid, "read_state", {}, 12, 1.0)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    tracing.end_turn(tid, "hello", messages)

    # summary.jsonl: exactly one line
    summary_lines = (tmp_path / "summary.jsonl").read_text("utf-8").strip().splitlines()
    assert len(summary_lines) == 1
    summary = json.loads(summary_lines[0])
    assert summary["turn_id"] == tid
    assert summary["total_tokens"] == 15
    assert summary["final_text_chars"] == len("hello")
    assert [c["name"] for c in summary["tool_calls"]] == ["read_state"]

    # full/<turn_id>.json: exact messages preserved
    full = json.loads((tmp_path / "full" / f"{tid}.json").read_text("utf-8"))
    assert full["turn_id"] == tid
    assert full["messages"] == messages

    # last_turn_summary reads back
    assert tracing.last_turn_summary()["turn_id"] == tid


def test_end_turn_is_best_effort_on_io_failure(tmp_path, monkeypatch, capsys):
    """If the file system blows up, end_turn must not raise."""
    monkeypatch.setattr(tracing, "TRACES_DIR", tmp_path / "does-not-exist")
    monkeypatch.setattr(tracing, "SUMMARY_FILE", tmp_path / "does-not-exist" / "summary.jsonl")
    monkeypatch.setattr(tracing, "FULL_DIR", tmp_path / "does-not-exist" / "full")

    def boom(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr(Path, "mkdir", boom)

    tid = tracing.start_turn("hi")
    tracing.end_turn(tid, "hello", [])  # must not raise
