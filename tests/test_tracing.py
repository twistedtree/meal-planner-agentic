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
