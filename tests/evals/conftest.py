"""Shared fixtures for real-model evals.

Each test gets a fresh, seeded state/ dir and a hook that writes a row to
traces/eval_runs.csv after each test. Run with: pytest -m eval
"""
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

import storage
import tracing

FIXTURES = Path(__file__).parent / "fixtures"
EVAL_RUNS_CSV = Path(__file__).resolve().parents[2] / "traces" / "eval_runs.csv"


@pytest.fixture
def fresh_state(tmp_path, monkeypatch):
    """Point storage at a temp dir seeded with profile + recipes fixtures."""
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    shutil.copy(FIXTURES / "profile_basic.json", tmp_path / "profile.json")
    shutil.copy(FIXTURES / "recipes_seed.json", tmp_path / "recipes.json")
    yield tmp_path


@pytest.fixture(autouse=True)
def _record_eval_run(request, monkeypatch, tmp_path_factory):
    """For every eval test, capture the trace summary and append a CSV row."""
    if "eval" not in request.keywords:
        yield
        return

    # Per-test trace directory so summaries don't collide.
    trace_dir = tmp_path_factory.mktemp("traces")
    monkeypatch.setattr(tracing, "TRACES_DIR", trace_dir)
    monkeypatch.setattr(tracing, "SUMMARY_FILE", trace_dir / "summary.jsonl")
    monkeypatch.setattr(tracing, "FULL_DIR", trace_dir / "full")

    yield

    # Aggregate this test's traces.
    summary_lines: list[dict] = []
    sf = trace_dir / "summary.jsonl"
    if sf.exists():
        for line in sf.read_text("utf-8").splitlines():
            line = line.strip()
            if line:
                summary_lines.append(json.loads(line))
    if not summary_lines:
        return

    total_p = sum(s.get("prompt_tokens", 0) for s in summary_lines)
    total_c = sum(s.get("completion_tokens", 0) for s in summary_lines)
    total_t = sum(s.get("total_tokens", 0) for s in summary_lines)
    total_ms = sum(s.get("latency_ms", 0) for s in summary_lines)
    tools = []
    for s in summary_lines:
        tools.extend(c["name"] for c in s.get("tool_calls", []))

    EVAL_RUNS_CSV.parent.mkdir(parents=True, exist_ok=True)
    is_new = not EVAL_RUNS_CSV.exists()
    with EVAL_RUNS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow([
                "timestamp", "test_name", "model",
                "prompt_tokens", "completion_tokens", "total_tokens",
                "latency_ms", "tool_calls", "passed",
            ])
        passed = not request.session.testsfailed  # rough; per-test pass would need a hook
        w.writerow([
            datetime.now(timezone.utc).isoformat(),
            request.node.nodeid,
            summary_lines[0].get("model", ""),
            total_p, total_c, total_t, total_ms,
            "|".join(tools), passed,
        ])
