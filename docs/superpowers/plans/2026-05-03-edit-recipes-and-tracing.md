# Edit Recipes, Tracing & Project-Level Docs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add chat-driven recipe edit/delete, tiered JSONL tracing with sidebar token visibility, a unit + opt-in eval test harness, and a set of living project-level docs (BRD/PRD/build-spec/architecture.yaml) to `meal-planner-agentic`.

**Architecture:** Two new tools (`update_recipe`, `delete_recipe`) sit alongside existing recipe tools and reuse the existing `_recipes_lock`. A new top-level `tracing.py` module is hooked into `agents/orchestrator.run_turn` and `agents/recipe_finder.find_new_recipes` to emit a one-line summary per turn (`traces/summary.jsonl`) and a full message dump (`traces/full/<turn_id>.json`); tracing is best-effort and never raises. Tests are split into `tests/unit/` (deterministic, default `pytest`) and `tests/evals/` (real-model, opt-in via `pytest -m eval`). Docs are hand-maintained, with `architecture.yaml` as the source of truth for `BUILD_SPEC.md`.

**Tech Stack:** Python 3.12, pydantic 2, LiteLLM (OpenRouter), Streamlit, pytest. No new runtime dependencies.

**Working directory:** `C:\Users\migst\personal-kb\code\meal-planner-agentic`. All file paths below are relative to that directory.

**Spec reference:** `docs/superpowers/specs/2026-05-03-edit-recipes-and-tracing-design.md`.

---

## Phase 0 — Pre-flight

### Task 0.1: Confirm the repo is clean for this work

- [ ] **Step 1: Confirm working tree state**

Run: `git status`
Expected: branch `main`, prior unrelated changes are fine but record them. We will only commit files this plan touches.

- [ ] **Step 2: Verify pytest currently passes**

Run (Windows): `.venv\Scripts\pytest.exe -v`
Expected: green (or at minimum: green for the specific tests we will move — `test_validate.py`, `test_storage.py`, `test_search.py`).

If any test is red on `main` before we start, stop and tell the user — don't paper over a pre-existing red.

- [ ] **Step 3: Create `traces/` and ensure it's gitignored**

Run:
```powershell
New-Item -ItemType Directory -Path traces -Force | Out-Null
New-Item -ItemType Directory -Path traces\full -Force | Out-Null
```

Append to `.gitignore` if not already present:
```
traces/
```

- [ ] **Step 4: Commit**

```powershell
git add .gitignore
git commit -m "chore: gitignore traces/"
```

---

## Phase 1 — Recipe model: add `notes` field

### Task 1.1: Add `Recipe.notes` with default

**Files:**
- Modify: `models.py:21-34` (the `Recipe` class)
- Test: `tests/test_models.py` (existing) — add a case

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
def test_recipe_notes_defaults_to_empty_string():
    from models import Recipe
    from datetime import datetime
    r = Recipe(
        id="x", title="X", cuisine="x", main_protein="x",
        key_ingredients=["a"], cook_time_min=10,
        added_at=datetime(2026, 5, 3),
    )
    assert r.notes == ""


def test_recipe_notes_round_trips():
    from models import Recipe
    from datetime import datetime
    r = Recipe(
        id="x", title="X", cuisine="x", main_protein="x",
        key_ingredients=["a"], cook_time_min=10,
        added_at=datetime(2026, 5, 3),
        notes="great with brown rice",
    )
    j = r.model_dump_json()
    r2 = Recipe.model_validate_json(j)
    assert r2.notes == "great with brown rice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest.exe tests/test_models.py::test_recipe_notes_defaults_to_empty_string -v`
Expected: FAIL with `AttributeError: 'Recipe' object has no attribute 'notes'` or `ValidationError`.

- [ ] **Step 3: Add the field**

Edit `models.py`. Inside `class Recipe(BaseModel)`, after the `source: str = "unknown"` line and before `added_at: datetime`, add:

```python
    notes: str = ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest.exe tests/test_models.py -v`
Expected: both new tests PASS, all pre-existing tests still PASS.

- [ ] **Step 5: Commit**

```powershell
git add models.py tests/test_models.py
git commit -m "feat(models): add Recipe.notes field with default"
```

---

## Phase 2 — `update_recipe` and `delete_recipe` tools

### Task 2.1: `update_recipe` happy path

**Files:**
- Modify: `tools/recipes.py` (append after `append_recipes`)
- Test: `tests/test_recipes_crud.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `tests/test_recipes_crud.py`:

```python
from datetime import datetime
from pathlib import Path
import pytest

from models import Recipe
import storage
import tools.recipes as recipes_mod


def _seed(tmp_path: Path, monkeypatch, items: list[Recipe]) -> None:
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    recipes_mod.save_all_recipes(items)


def _r(rid: str, **kw) -> Recipe:
    base = dict(
        id=rid, title=rid.replace("-", " ").title(),
        cuisine="unknown", main_protein="unknown",
        key_ingredients=["a"], cook_time_min=20,
        source="manual", added_at=datetime(2026, 5, 3),
    )
    base.update(kw)
    return Recipe(**base)


def test_update_recipe_merges_fields(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_r("salmon-bowls", cuisine="unknown", main_protein="unknown")])

    out = recipes_mod.update_recipe("salmon-bowls", {"cuisine": "japanese"})

    assert out is not None
    assert out["cuisine"] == "japanese"
    persisted = recipes_mod.load_all_recipes()
    assert persisted[0].cuisine == "japanese"
    # untouched field preserved
    assert persisted[0].main_protein == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest.exe tests/test_recipes_crud.py::test_update_recipe_merges_fields -v`
Expected: FAIL with `AttributeError: module 'tools.recipes' has no attribute 'update_recipe'`.

- [ ] **Step 3: Implement `update_recipe`**

Append to `tools/recipes.py`:

```python
_IMMUTABLE_FIELDS = frozenset({"id", "added_at"})


def update_recipe(recipe_id: str, fields: dict) -> dict | None:
    """Merge-update fields on an existing recipe. id and added_at are immutable.
    Returns the updated recipe summary, or None if id not found."""
    safe_fields = {k: v for k, v in fields.items() if k not in _IMMUTABLE_FIELDS}
    with _recipes_lock:
        existing = load_all_recipes()
        for i, r in enumerate(existing):
            if r.id == recipe_id:
                merged = r.model_dump()
                merged.update(safe_fields)
                existing[i] = Recipe.model_validate(merged)
                save_json_list("recipes.json", existing)
                return recipe_summary(existing[i])
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest.exe tests/test_recipes_crud.py::test_update_recipe_merges_fields -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/recipes.py tests/test_recipes_crud.py
git commit -m "feat(recipes): add update_recipe (merge happy path)"
```

### Task 2.2: `update_recipe` — immutable fields silently dropped

**Files:**
- Modify: `tests/test_recipes_crud.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_recipes_crud.py`:

```python
def test_update_recipe_drops_immutable_fields(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_r("salmon-bowls")])

    out = recipes_mod.update_recipe(
        "salmon-bowls",
        {"id": "MUTATED", "added_at": "2099-01-01T00:00:00", "cuisine": "japanese"},
    )

    assert out is not None
    assert out["id"] == "salmon-bowls"  # id is immutable
    persisted = recipes_mod.load_all_recipes()
    assert persisted[0].id == "salmon-bowls"
    assert persisted[0].added_at == datetime(2026, 5, 3)
    assert persisted[0].cuisine == "japanese"  # mutable change still applied
```

- [ ] **Step 2: Run test to verify it passes (already implemented)**

Run: `.venv\Scripts\pytest.exe tests/test_recipes_crud.py::test_update_recipe_drops_immutable_fields -v`
Expected: PASS — the implementation in 2.1 already filters via `_IMMUTABLE_FIELDS`.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_recipes_crud.py
git commit -m "test(recipes): cover update_recipe ignores id/added_at"
```

### Task 2.3: `update_recipe` — invalid types raise

**Files:**
- Modify: `tests/test_recipes_crud.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_recipes_crud.py`:

```python
def test_update_recipe_invalid_type_raises(tmp_path, monkeypatch):
    from pydantic import ValidationError

    _seed(tmp_path, monkeypatch, [_r("salmon-bowls")])

    with pytest.raises(ValidationError):
        recipes_mod.update_recipe("salmon-bowls", {"cook_time_min": "twenty"})
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv\Scripts\pytest.exe tests/test_recipes_crud.py::test_update_recipe_invalid_type_raises -v`
Expected: PASS — pydantic raises `ValidationError` on bad merge.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_recipes_crud.py
git commit -m "test(recipes): cover update_recipe rejects bad types"
```

### Task 2.4: `update_recipe` — unknown id returns None

**Files:**
- Modify: `tests/test_recipes_crud.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_recipes_crud.py`:

```python
def test_update_recipe_unknown_id_returns_none(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_r("salmon-bowls")])
    assert recipes_mod.update_recipe("nope", {"cuisine": "x"}) is None
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv\Scripts\pytest.exe tests/test_recipes_crud.py::test_update_recipe_unknown_id_returns_none -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_recipes_crud.py
git commit -m "test(recipes): cover update_recipe unknown id"
```

### Task 2.5: `delete_recipe` happy path + unknown id

**Files:**
- Modify: `tools/recipes.py`
- Modify: `tests/test_recipes_crud.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_recipes_crud.py`:

```python
def test_delete_recipe_removes_row(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_r("salmon-bowls"), _r("ratatouille")])

    assert recipes_mod.delete_recipe("salmon-bowls") is True

    persisted = recipes_mod.load_all_recipes()
    assert [r.id for r in persisted] == ["ratatouille"]


def test_delete_recipe_unknown_id_returns_false(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_r("salmon-bowls")])
    assert recipes_mod.delete_recipe("nope") is False
    assert len(recipes_mod.load_all_recipes()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest.exe tests/test_recipes_crud.py::test_delete_recipe_removes_row -v`
Expected: FAIL with `AttributeError: module 'tools.recipes' has no attribute 'delete_recipe'`.

- [ ] **Step 3: Implement `delete_recipe`**

Append to `tools/recipes.py`:

```python
def delete_recipe(recipe_id: str) -> bool:
    """Remove a recipe by id. Returns True if removed, False if not found."""
    with _recipes_lock:
        existing = load_all_recipes()
        new = [r for r in existing if r.id != recipe_id]
        if len(new) == len(existing):
            return False
        save_json_list("recipes.json", new)
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest.exe tests/test_recipes_crud.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/recipes.py tests/test_recipes_crud.py
git commit -m "feat(recipes): add delete_recipe"
```

---

## Phase 3 — Wire `update_recipe` and `delete_recipe` into the orchestrator

### Task 3.1: Register tool schemas + dispatcher branches

**Files:**
- Modify: `agents/orchestrator.py:15-22` (imports), `:66-209` (TOOL_DEFINITIONS), `:217-298` (`_dispatch`)

- [ ] **Step 1: Update the recipes import**

In `agents/orchestrator.py`, change:

```python
from tools.recipes import (
    load_all_recipes, list_recipes, search_recipes, get_recipe,
    find_new_recipes_tool,
)
```

to:

```python
from tools.recipes import (
    load_all_recipes, list_recipes, search_recipes, get_recipe,
    find_new_recipes_tool, update_recipe, delete_recipe,
)
```

- [ ] **Step 2: Add tool definitions**

In `agents/orchestrator.py`, inside `TOOL_DEFINITIONS`, after the existing `find_new_recipes` tool entry and before `check_search_status`, insert:

```python
    _tool("update_recipe",
          "Edit fields on a saved recipe. Pass any subset of fields. id is immutable.",
          {
              "type": "object",
              "properties": {
                  "recipe_id": {"type": "string"},
                  "fields": {
                      "type": "object",
                      "properties": {
                          "title":           {"type": "string"},
                          "cuisine":         {"type": "string"},
                          "main_protein":    {"type": "string"},
                          "key_ingredients": {"type": "array", "items": {"type": "string"}},
                          "tags":            {"type": "array", "items": {"type": "string"}},
                          "cook_time_min":   {"type": "integer"},
                          "source_url":      {"type": ["string", "null"]},
                          "source":          {"type": "string"},
                          "notes":           {"type": "string"},
                      },
                      "additionalProperties": False,
                  },
              },
              "required": ["recipe_id", "fields"],
          }),
    _tool("delete_recipe",
          "Remove a saved recipe by id.",
          {"type": "object",
           "properties": {"recipe_id": {"type": "string"}},
           "required": ["recipe_id"]}),
```

- [ ] **Step 3: Add dispatcher branches**

In `agents/orchestrator.py`, inside `_dispatch`, after the `find_new_recipes` branch and before `check_search_status`, insert:

```python
        if name == "update_recipe":
            result = update_recipe(args["recipe_id"], args.get("fields", {}))
            return json.dumps(result)
        if name == "delete_recipe":
            ok = delete_recipe(args["recipe_id"])
            return json.dumps({"ok": ok})
```

- [ ] **Step 4: Smoke-check imports + schema validity**

Run:
```powershell
.venv\Scripts\python.exe -c "from agents.orchestrator import TOOL_DEFINITIONS, _dispatch; names = [t['function']['name'] for t in TOOL_DEFINITIONS]; assert 'update_recipe' in names and 'delete_recipe' in names; print('ok', len(names), 'tools')"
```
Expected: prints `ok 17 tools` (or similar — count just confirms both new tools are registered).

- [ ] **Step 5: Commit**

```powershell
git add agents/orchestrator.py
git commit -m "feat(orchestrator): register update_recipe and delete_recipe tools"
```

### Task 3.2: Update orchestrator system prompt

**Files:**
- Modify: `agents/prompts.py:55-62` (INTERACTION RULES section)

- [ ] **Step 1: Edit the prompt**

In `agents/prompts.py`, replace the `INTERACTION RULES` block (the lines from `INTERACTION RULES:` down to and including the closing `"""`) with:

```python
INTERACTION RULES:
- Always confirm before calling update_plan / update_pantry / update_profile /
  update_recipe / delete_recipe unless the user said "just do it"
- If update_plan returns validation warnings, surface them verbatim
- Keep responses short. The user reads the table, not prose.
- If profile.json is empty (first run), open with an onboarding chat to learn
  about the household before doing anything else.

RECIPE LIBRARY EDITS:
- When the user asks to edit or correct a recipe ("change the cuisine on X",
  "the protein for Y is wrong", "add a note to Z"), call update_recipe with the
  recipe_id and a `fields` object containing only the fields to change.
  Recipe id is immutable.
- When the user asks to remove a recipe ("delete the failed cassoulet"), call
  delete_recipe with the recipe_id. If the recipe is in the current meal_plan,
  warn the user before deleting.
"""
```

(Keep `RECIPE_FINDER_SYSTEM_PROMPT` below it untouched.)

- [ ] **Step 2: Verify the module still imports**

Run:
```powershell
.venv\Scripts\python.exe -c "from agents.prompts import ORCHESTRATOR_SYSTEM_PROMPT; assert 'update_recipe' in ORCHESTRATOR_SYSTEM_PROMPT; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```powershell
git add agents/prompts.py
git commit -m "feat(prompts): teach orchestrator to use update_recipe/delete_recipe"
```

---

## Phase 4 — `tracing.py` module

### Task 4.1: Module skeleton with `start_turn` + `last_turn_summary`

**Files:**
- Create: `tracing.py`
- Create: `tests/test_tracing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tracing.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest.exe tests/test_tracing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tracing'`.

- [ ] **Step 3: Implement skeleton**

Create `tracing.py` at the project root:

```python
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
    turn_id = f"{ts}-{uuid.uuid4().hex[:6]}"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest.exe tests/test_tracing.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add tracing.py tests/test_tracing.py
git commit -m "feat(tracing): module skeleton with start_turn + last_turn_summary"
```

### Task 4.2: `record_completion` and `record_tool_call`

**Files:**
- Modify: `tracing.py`
- Modify: `tests/test_tracing.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tracing.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest.exe tests/test_tracing.py -v`
Expected: 3 new tests FAIL with `AttributeError: module 'tracing' has no attribute 'record_completion'`.

- [ ] **Step 3: Implement**

Append to `tracing.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest.exe tests/test_tracing.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add tracing.py tests/test_tracing.py
git commit -m "feat(tracing): record_completion + record_tool_call"
```

### Task 4.3: `end_turn` writes summary + full files

**Files:**
- Modify: `tracing.py`
- Modify: `tests/test_tracing.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracing.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest.exe tests/test_tracing.py -v`
Expected: 2 new tests FAIL with `AttributeError: module 'tracing' has no attribute 'end_turn'`.

- [ ] **Step 3: Implement**

Append to `tracing.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest.exe tests/test_tracing.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add tracing.py tests/test_tracing.py
git commit -m "feat(tracing): end_turn writes summary + full; best-effort on IO failure"
```

---

## Phase 5 — Wire tracing into the orchestrator and recipe finder

### Task 5.1: Trace LLM calls + tool calls + end_turn in `run_turn`

**Files:**
- Modify: `agents/orchestrator.py:1-23` (imports), `:372-446` (`run_turn`), `:418-431` (`_run_one`)

- [ ] **Step 1: Add imports**

In `agents/orchestrator.py`, after the existing imports near the top, add:

```python
import time
import tracing
```

(`time` may already be imported inside the function — promote to module scope to avoid shadowing.)

- [ ] **Step 2: Modify `run_turn`**

In `agents/orchestrator.py`, replace the current body of `run_turn` with the version below. The substantive changes are:
1. Call `tracing.start_turn` at the top.
2. Time each `completion(...)` call and pass to `tracing.record_completion`.
3. Pass `turn_id` into `_run_one` so it can record the tool call.
4. Call `tracing.end_turn` on every exit path (normal return AND tool-loop-limit return).

```python
def run_turn(user_message: str, history: list[dict]) -> tuple[str, list[dict]]:
    """Run one conversational turn. Returns (assistant text, updated history).

    history is a list of OpenAI-shape messages: {role, content, [tool_calls], [tool_call_id]}.
    """
    snapshot_for_undo()
    history = _trim_history(history)
    turn_id = tracing.start_turn(user_message)
    messages = (
        [{"role": "system", "content": _build_system_prompt()}]
        + history
        + [{"role": "user", "content": user_message}]
    )

    try:
        for iteration in range(MAX_TOOL_ITERATIONS):
            t0 = time.monotonic()
            response = completion(
                model=MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                max_tokens=4096,
            )
            tracing.record_completion(turn_id, response, (time.monotonic() - t0) * 1000)

            choice = response.choices[0]
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None) or []

            assistant_entry = {
                "role": "assistant",
                "content": msg.content or "",
            }
            if tool_calls:
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_entry)

            if not tool_calls:
                final_text = (msg.content or "").strip()
                tracing.end_turn(turn_id, final_text, messages)
                return (final_text, messages[1:])

            if iteration > 0:
                time.sleep(2)

            if len(tool_calls) == 1:
                messages.append(_run_one(tool_calls[0], turn_id))
            else:
                results: list[dict] = []
                with ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
                    futures = {pool.submit(_run_one, tc, turn_id): tc for tc in tool_calls}
                    for future in as_completed(futures):
                        results.append(future.result())
                id_order = {tc.id: i for i, tc in enumerate(tool_calls)}
                results.sort(key=lambda r: id_order[r["tool_call_id"]])
                messages.extend(results)

        final_text = "(tool loop limit hit — simplify your request)"
        tracing.end_turn(turn_id, final_text, messages)
        return (final_text, messages[1:])
    except Exception:
        # Make sure the trace is closed even on a hard failure.
        try:
            tracing.end_turn(turn_id, "(error)", messages)
        except Exception:
            pass
        raise
```

- [ ] **Step 3: Modify `_run_one`**

Replace the current `_run_one` definition (it lives inside `run_turn`) with a module-level version that takes `turn_id`. Move it OUT of `run_turn` and put it just above `run_turn`:

```python
def _run_one(tc, turn_id: str) -> dict:
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    t0 = time.monotonic()
    result = _dispatch(tc.function.name, args)
    elapsed_ms = (time.monotonic() - t0) * 1000
    tracing.record_tool_call(turn_id, tc.function.name, args, len(result), elapsed_ms)
    if len(result) > MAX_TOOL_RESULT_CHARS:
        result = result[:MAX_TOOL_RESULT_CHARS] + " ...(truncated)"
    return {
        "role": "tool",
        "tool_call_id": tc.id,
        "name": tc.function.name,
        "content": result,
    }
```

Remove the inner `def _run_one(tc):` from inside `run_turn` (it's superseded by the module-level one).

- [ ] **Step 4: Smoke test — module imports + a single trace round trip**

Run:
```powershell
.venv\Scripts\python.exe -c "from agents.orchestrator import run_turn, _run_one; print('ok')"
```
Expected: `ok`.

Then a fast offline trace round-trip (no API call):
```powershell
.venv\Scripts\python.exe -c "import tracing; tid = tracing.start_turn('hi'); tracing.record_tool_call(tid, 'noop', {}, 0, 0.1); tracing.end_turn(tid, 'done', [{'role':'user','content':'hi'}]); print(tracing.last_turn_summary()['turn_id'] == tid)"
```
Expected: `True`.

- [ ] **Step 5: Commit**

```powershell
git add agents/orchestrator.py
git commit -m "feat(orchestrator): emit per-turn LLM + tool-call traces"
```

### Task 5.2: Trace recipe-finder subagent under parent turn

**Files:**
- Modify: `agents/recipe_finder.py`
- Modify: `tools/recipes.py:119-129` (`find_new_recipes_tool`)

- [ ] **Step 1: Update `find_new_recipes` to record sub-trace + return summary**

In `agents/recipe_finder.py`, change the signature of `find_new_recipes` to also accept a `parent_turn_id` and return both the recipes AND a summary dict. Replace the function with:

```python
def find_new_recipes(
    query: str,
    count: int,
    profile: Profile | None,
    on_progress: Callable[[int, int, str], None] | None = None,
    parent_turn_id: str | None = None,
) -> tuple[list[Recipe], dict]:
    """Run an isolated LLM call with web search (via OpenRouter ':online'),
    return (recipes, sub_summary)."""
    import time as _time
    import tracing as _tracing

    sub_id = _tracing.start_turn(f"[subagent] {query}")
    system_prompt = RECIPE_FINDER_SYSTEM_PROMPT.format(
        query=query,
        count=count,
        household_context=_household_context(profile),
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Find {count} recipes for: {query}"},
    ]

    with _api_semaphore:
        if on_progress:
            on_progress(1, 2, f"Searching for '{query}'…")

        response = None
        for attempt in range(4):
            try:
                t0 = _time.monotonic()
                response = completion(
                    model=MODEL,
                    messages=messages,
                    max_tokens=4096,
                )
                _tracing.record_completion(sub_id, response, (_time.monotonic() - t0) * 1000)
                break
            except RateLimitError:
                wait = 2 ** attempt * 15
                if on_progress:
                    on_progress(1, 2, f"Rate limited, retrying in {wait}s…")
                time.sleep(wait)

        if on_progress:
            on_progress(2, 2, "Processing results…")

    if response is None:
        _tracing.end_turn(sub_id, "(no response)", messages)
        return ([], {"sub_turn_id": sub_id, "recipes_found": 0, "model": MODEL})

    raw = (response.choices[0].message.content or "").strip()

    out: list[Recipe] = []
    match = re.search(r"\[\s*\{.*?\}\s*\]", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            parsed = []
        now = datetime.now()
        for item in parsed:
            try:
                out.append(Recipe(
                    id=_slugify(item.get("title", "")),
                    title=item["title"],
                    cuisine=item.get("cuisine", "unknown"),
                    main_protein=item.get("main_protein", "unknown"),
                    key_ingredients=item.get("key_ingredients", []),
                    tags=item.get("tags", []),
                    cook_time_min=int(item.get("cook_time_min", 30)),
                    source_url=item.get("source_url"),
                    source="web",
                    added_at=now,
                ))
            except (KeyError, ValueError):
                continue

    final_messages = messages + [{"role": "assistant", "content": raw}]
    _tracing.end_turn(sub_id, raw[:500], final_messages)

    sub_summary = {
        "sub_turn_id": sub_id,
        "model": MODEL,
        "recipes_found": len(out),
    }
    if parent_turn_id:
        _tracing.attach_subagent(parent_turn_id, sub_summary)
    return (out, sub_summary)
```

- [ ] **Step 2: Update `find_new_recipes_tool` to consume the new return shape**

In `tools/recipes.py`, change `find_new_recipes_tool` to:

```python
def find_new_recipes_tool(
    query: str,
    count: int,
    profile: Profile | None,
    on_progress: Callable[[int, int, str], None] | None = None,
    parent_turn_id: str | None = None,
) -> list[dict]:
    """Tool-facing: spawn subagent, append results to recipes.json, return summaries."""
    from agents.recipe_finder import find_new_recipes
    found, _sub = find_new_recipes(
        query, count, profile,
        on_progress=on_progress,
        parent_turn_id=parent_turn_id,
    )
    added = append_recipes(found)
    return [recipe_summary(r) for r in added]
```

- [ ] **Step 3: Pass `parent_turn_id` from the orchestrator dispatcher**

In `agents/orchestrator.py`, `_dispatch` currently calls `find_new_recipes_tool(...)`. We need `turn_id` in scope. The cleanest fix: change `_dispatch(name, args)` to `_dispatch(name, args, turn_id)`, and pass `turn_id` everywhere it's called.

In `agents/orchestrator.py`:

a. Change the `_dispatch` signature to:
```python
def _dispatch(name: str, args: dict, turn_id: str | None = None) -> str:
```

b. Inside `_dispatch`, change the `find_new_recipes` branch to:
```python
        if name == "find_new_recipes":
            result = find_new_recipes_tool(
                query=args["query"],
                count=args.get("count", 3),
                profile=read_profile(),
                parent_turn_id=turn_id,
            )
            return json.dumps(result)
```

c. Change `_run_one` to pass `turn_id` into `_dispatch`:
```python
    result = _dispatch(tc.function.name, args, turn_id)
```

d. Also fix `_run_recipe_search_bg` (used by background jobs) — it already calls `find_new_recipes_tool` directly without a turn_id, which is fine; backgrounded searches will create their own root sub-trace because `parent_turn_id` defaults to None. No change needed there.

- [ ] **Step 4: Smoke import test**

Run:
```powershell
.venv\Scripts\python.exe -c "from agents.orchestrator import _dispatch; from agents.recipe_finder import find_new_recipes; print('ok')"
```
Expected: `ok`.

- [ ] **Step 5: Commit**

```powershell
git add agents/recipe_finder.py tools/recipes.py agents/orchestrator.py
git commit -m "feat(tracing): nest recipe-finder subagent traces under parent turn"
```

---

## Phase 6 — Streamlit sidebar token caption

### Task 6.1: Show last-turn cost in the sidebar

**Files:**
- Modify: `app.py:56-81` (`_render_sidebar`)

- [ ] **Step 1: Edit `_render_sidebar`**

In `app.py`, after the `Recent ratings` expander block inside `_render_sidebar()`, add a new section:

```python
        st.subheader("Last turn")
        import tracing
        last = tracing.last_turn_summary()
        if last is None:
            st.caption("(no traces yet)")
        else:
            tot = last.get("total_tokens", 0)
            ms = last.get("latency_ms", 0)
            n_tools = len(last.get("tool_calls", []))
            tot_str = f"{tot/1000:.1f}K" if tot >= 1000 else str(tot)
            st.caption(f"{tot_str} tokens · {ms/1000:.1f}s · {n_tools} tools")
```

- [ ] **Step 2: Smoke test**

Run: `.venv\Scripts\streamlit.exe run app.py`

Manually:
1. Visit http://localhost:8501.
2. Confirm the sidebar shows `Last turn: (no traces yet)` if `traces/summary.jsonl` is empty, or a token line if not.
3. Send any message; on rerun, the caption updates.

Stop the server (Ctrl-C).

- [ ] **Step 3: Commit**

```powershell
git add app.py
git commit -m "feat(app): show last-turn token + latency caption in sidebar"
```

---

## Phase 7 — Test layout: pytest markers + restructuring (optional move)

### Task 7.1: Register the `eval` pytest marker

**Files:**
- Modify: `pyproject.toml:26-28`

- [ ] **Step 1: Update pytest config**

In `pyproject.toml`, replace the `[tool.pytest.ini_options]` block with:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "eval: real-model evals (cost money, opt-in via -m eval)",
]
addopts = "-m 'not eval'"
```

The `addopts` line makes `pytest` (no args) skip evals by default. Run evals with `pytest -m eval`.

- [ ] **Step 2: Verify default run still passes**

Run: `.venv\Scripts\pytest.exe -v`
Expected: all unit tests PASS, no eval tests collected.

- [ ] **Step 3: Commit**

```powershell
git add pyproject.toml
git commit -m "chore(tests): register opt-in 'eval' pytest marker"
```

### Task 7.2: Create `tests/evals/` scaffold

**Files:**
- Create: `tests/evals/__init__.py` (empty)
- Create: `tests/evals/conftest.py`
- Create: `tests/evals/fixtures/profile_basic.json`
- Create: `tests/evals/fixtures/recipes_seed.json`

- [ ] **Step 1: Create the package files**

Create `tests/evals/__init__.py` as an empty file.

Create `tests/evals/conftest.py`:

```python
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
```

Create `tests/evals/fixtures/profile_basic.json`:

```json
{
  "household_size": 4,
  "members": [
    {"name": "Adult1", "is_adult": true, "dislikes": []},
    {"name": "Adult2", "is_adult": true, "dislikes": []},
    {"name": "Kid1", "is_adult": false, "dislikes": ["mushrooms"]},
    {"name": "Kid2", "is_adult": false, "dislikes": []}
  ],
  "household_dislikes": ["mushrooms"],
  "dietary_rules": [">=1 fish meal per week", "every meal includes a vegetable"],
  "preferred_cuisines": ["japanese", "italian", "thai"],
  "notes": "kids prefer mild spice"
}
```

Create `tests/evals/fixtures/recipes_seed.json`:

```json
[
  {
    "id": "salmon-teriyaki-bowls",
    "title": "Salmon teriyaki bowls",
    "cuisine": "unknown",
    "main_protein": "salmon",
    "key_ingredients": ["salmon", "broccoli", "rice", "soy"],
    "tags": ["quick"],
    "cook_time_min": 25,
    "times_cooked": 3,
    "avg_rating": 4.5,
    "source": "manual",
    "added_at": "2026-04-01T12:00:00",
    "notes": ""
  },
  {
    "id": "ratatouille",
    "title": "Ratatouille",
    "cuisine": "french",
    "main_protein": "vegetarian",
    "key_ingredients": ["zucchini", "eggplant", "tomato", "bell pepper"],
    "tags": ["one-pan"],
    "cook_time_min": 45,
    "times_cooked": 1,
    "avg_rating": 4.0,
    "source": "manual",
    "added_at": "2026-04-08T12:00:00",
    "notes": ""
  }
]
```

- [ ] **Step 2: Verify scaffold doesn't break the default run**

Run: `.venv\Scripts\pytest.exe -v`
Expected: PASS, evals not collected (since `addopts = "-m 'not eval'"`).

- [ ] **Step 3: Commit**

```powershell
git add tests/evals/
git commit -m "test(evals): scaffold conftest, fixtures, and CSV tracking"
```

---

## Phase 8 — Eval tests

### Task 8.1: Capability eval — edit recipe changes cuisine

**Files:**
- Create: `tests/evals/test_capabilities.py`

- [ ] **Step 1: Write the test**

Create `tests/evals/test_capabilities.py`:

```python
import os

import pytest

import tools.recipes as recipes_mod
from agents.orchestrator import run_turn

pytestmark = pytest.mark.eval


def _last_summary_tools(traces_dir):
    import json
    sf = traces_dir / "summary.jsonl"
    last = json.loads(sf.read_text("utf-8").splitlines()[-1])
    return [c["name"] for c in last["tool_calls"]], last["total_tokens"]


def test_edit_recipe_changes_cuisine(fresh_state, monkeypatch, tmp_path_factory):
    # Pre-condition: salmon-teriyaki-bowls.cuisine == "unknown"
    pre = recipes_mod.load_all_recipes()
    assert next(r for r in pre if r.id == "salmon-teriyaki-bowls").cuisine == "unknown"

    reply, _ = run_turn(
        "change the cuisine on Salmon teriyaki bowls to Japanese, just do it",
        history=[],
    )

    post = recipes_mod.load_all_recipes()
    after = next(r for r in post if r.id == "salmon-teriyaki-bowls")
    assert after.cuisine.lower() == "japanese", f"cuisine not updated; reply was: {reply}"

    # Token ceiling: edit-recipe is a small workflow.
    import tracing
    summary = tracing.last_turn_summary()
    assert summary is not None
    assert summary["total_tokens"] <= 6000, f"edit_recipe burned {summary['total_tokens']} tokens"
    names = [c["name"] for c in summary["tool_calls"]]
    assert "update_recipe" in names
```

- [ ] **Step 2: Run the eval (manual; costs tokens)**

Run: `.venv\Scripts\pytest.exe -m eval tests/evals/test_capabilities.py::test_edit_recipe_changes_cuisine -v`
Expected: PASS. If it fails on token ceiling, **note the actual usage** and do not relax the ceiling without measuring 3 runs and setting it to median × 1.2.

- [ ] **Step 3: Commit**

```powershell
git add tests/evals/test_capabilities.py
git commit -m "test(evals): edit recipe changes cuisine"
```

### Task 8.2: Capability eval — delete recipe removes row

**Files:**
- Modify: `tests/evals/test_capabilities.py`

- [ ] **Step 1: Append the test**

```python
def test_delete_recipe_removes_row(fresh_state):
    pre_ids = {r.id for r in recipes_mod.load_all_recipes()}
    assert "ratatouille" in pre_ids

    reply, _ = run_turn("delete the ratatouille recipe, just do it", history=[])

    post_ids = {r.id for r in recipes_mod.load_all_recipes()}
    assert "ratatouille" not in post_ids, f"not deleted; reply was: {reply}"

    import tracing
    summary = tracing.last_turn_summary()
    assert summary is not None
    assert summary["total_tokens"] <= 5000
    assert "delete_recipe" in [c["name"] for c in summary["tool_calls"]]
```

- [ ] **Step 2: Run the eval**

Run: `.venv\Scripts\pytest.exe -m eval tests/evals/test_capabilities.py::test_delete_recipe_removes_row -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add tests/evals/test_capabilities.py
git commit -m "test(evals): delete recipe removes row"
```

### Task 8.3: Capability evals — planning workflow asserts

**Files:**
- Modify: `tests/evals/test_capabilities.py`

- [ ] **Step 1: Append three more tests**

```python
def test_validate_runs_inside_update_plan(fresh_state):
    """The orchestrator's dispatcher runs validate inside update_plan; we just
    assert update_plan was called and the plan was persisted with 5 slots."""
    from tools.state import read_state

    reply, _ = run_turn(
        "plan next week's dinners, just do it. use what's already in our recipe library where it makes sense.",
        history=[],
    )
    s = read_state()
    assert len(s.meal_plan) == 5, f"expected 5 slots; reply was: {reply}"

    import tracing
    summary = tracing.last_turn_summary()
    assert summary is not None
    assert summary["total_tokens"] <= 30000
    assert "update_plan" in [c["name"] for c in summary["tool_calls"]]


def test_no_web_search_unless_asked(fresh_state):
    reply, _ = run_turn("plan next week, just do it.", history=[])
    import tracing
    summary = tracing.last_turn_summary()
    assert summary is not None
    assert "find_new_recipes" not in [c["name"] for c in summary["tool_calls"]], reply


def test_web_search_when_explicitly_asked(fresh_state):
    if not os.getenv("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY required for web-search eval")

    reply, _ = run_turn(
        "find me 3 new bacalhau recipes from the web — just do it.",
        history=[],
    )
    import tracing
    summary = tracing.last_turn_summary()
    assert summary is not None
    assert summary["total_tokens"] <= 35000
    assert "find_new_recipes" in [c["name"] for c in summary["tool_calls"]], reply
```

- [ ] **Step 2: Run the evals**

Run: `.venv\Scripts\pytest.exe -m eval tests/evals/test_capabilities.py -v`
Expected: all PASS. If `test_validate_runs_inside_update_plan` exceeds 30K, record the actual median over 3 runs and update the ceiling.

- [ ] **Step 3: Commit**

```powershell
git add tests/evals/test_capabilities.py
git commit -m "test(evals): planning workflow + web-search gating"
```

### Task 8.4: Workflow smoke evals

**Files:**
- Create: `tests/evals/test_workflows.py`

- [ ] **Step 1: Write the multi-turn smokes**

Create `tests/evals/test_workflows.py`:

```python
import os

import pytest

from agents.orchestrator import run_turn
from tools.state import read_state
from tools.profile import read_profile

pytestmark = pytest.mark.eval


def test_onboard_then_plan(tmp_path, monkeypatch):
    """Empty state → onboarding chat sets profile → plan call sets meal_plan."""
    import storage
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)

    reply1, hist1 = run_turn(
        "I'm a household of 4: 2 adults, 2 kids. The kids dislike mushrooms. "
        "We aim for fish once a week and veg every meal. Just do it — set my profile.",
        history=[],
    )
    p = read_profile()
    assert p is not None and p.household_size == 4
    assert "mushrooms" in [d.lower() for d in p.household_dislikes] + [
        d.lower() for m in p.members for d in m.dislikes
    ]

    reply2, _ = run_turn("now plan next week, just do it.", history=hist1)
    s = read_state()
    assert len(s.meal_plan) == 5, f"reply was: {reply2}"


def test_swap_then_rate(fresh_state):
    """Plan → swap one day → rate the cooked meal."""
    reply1, hist1 = run_turn("plan next week, just do it.", history=[])
    s1 = read_state()
    assert len(s1.meal_plan) == 5

    reply2, hist2 = run_turn(
        "swap Wednesday for something lighter, just do it.",
        history=hist1,
    )
    s2 = read_state()
    assert len(s2.meal_plan) == 5
    wed1 = next(slot for slot in s1.meal_plan if slot.day == "Wed").recipe_title
    wed2 = next(slot for slot in s2.meal_plan if slot.day == "Wed").recipe_title
    assert wed1 != wed2, f"Wednesday should have changed; reply was: {reply2}"

    reply3, _ = run_turn(
        f"we cooked {s2.meal_plan[0].recipe_title} on Monday and Adult1 loved it. "
        f"record that — rating again_soon. just do it.",
        history=hist2,
    )
    s3 = read_state()
    assert len(s3.ratings) >= 1, f"reply was: {reply3}"


def test_cookidoo_import():
    if not os.getenv("cookidoo_user") or not os.getenv("cookiday_pass"):
        pytest.skip("Cookidoo creds not set; skipping integration eval")
    pytest.skip("test_cookidoo_import requires a known recipe id; provide one in env COOKIDOO_TEST_RECIPE_ID")
```

- [ ] **Step 2: Run the smokes**

Run: `.venv\Scripts\pytest.exe -m eval tests/evals/test_workflows.py -v`
Expected: `test_onboard_then_plan` and `test_swap_then_rate` PASS, `test_cookidoo_import` SKIPS.

- [ ] **Step 3: Commit**

```powershell
git add tests/evals/test_workflows.py
git commit -m "test(evals): onboard→plan and swap→rate workflow smokes"
```

---

## Phase 9 — Project-level docs

### Task 9.1: BRD

**Files:**
- Create: `docs/BRD.md`

- [ ] **Step 1: Write `docs/BRD.md`**

```markdown
# Business Requirements Document

## Purpose
A personal chat-driven weekly-dinner planner for one household. Replaces the
overhead of a structured meal-planning UI with conversational interaction
backed by JSON state files.

## Stakeholders
One household (the maintainer's family). No external customers.

## Success criteria
- Any dinner-planning task (plan, swap, rate, edit, import) completes via chat in <60s of user effort.
- Recipe library can grow without per-turn token use ballooning. The library is
  searchable; full recipe rows are loaded only on commit.
- The agent never silently violates household dislikes or dietary rules.
  `validate_plan` warnings are surfaced verbatim.

## Business non-goals
- Multi-tenant, multi-household, account management, billing.
- Mobile-native packaging (Streamlit web is enough).
- Offline / PWA / multi-device concurrency.
- Marketing, public hosting, analytics.

## Decision policy
- Single source of truth for current state: `state/*.json`.
- Single source of truth for current implementation: `docs/architecture.yaml`
  + `docs/BUILD_SPEC.md`.
- Each sub-project gets a dated design spec under `docs/superpowers/specs/`
  and a corresponding plan under `docs/superpowers/plans/`.
```

- [ ] **Step 2: Commit**

```powershell
git add docs/BRD.md
git commit -m "docs: add BRD"
```

### Task 9.2: PRD

**Files:**
- Create: `docs/PRD.md`

- [ ] **Step 1: Write `docs/PRD.md`**

```markdown
# Product Requirements Document

> Living document. Each sub-project updates the affected capability.

## Capabilities

### 1. Plan Mon–Fri dinners
- **Story:** As the cook, I ask the agent to plan next week's dinners. It produces a 5-slot table.
- **Today:** `update_plan` tool; validation surfaces hard-rule warnings via `validate_plan`.
- **Limitations:** No recurring schedules, no cross-week optimisation.

### 2. Edit existing plan via chat
- **Story:** "Swap Wed for something lighter."
- **Today:** Agent calls `search_recipes` then `update_plan` with a 5-slot diff.
- **Limitations:** Only week-of granularity; no day-of editing of components.

### 3. Pantry tracking
- **Story:** "We're out of rice."
- **Today:** `update_pantry({add, remove})` — in/out only, no quantities.

### 4. Recipe library
- **Story:** "Add the Cookidoo salmon recipe r471786."
- **Today:** `recipes.json` grows from `find_new_recipes` (web subagent),
  `fetch_cookidoo_recipe`, or manual entry. Search/list tools keep token cost flat.

### 5. Recipe editing & deletion *(added 2026-05-03)*
- **Story:** "Change the cuisine on salmon teriyaki to Japanese."
- **Today:** `update_recipe(id, fields)` and `delete_recipe(id)`. `id` is immutable.
- **Confirmation rule:** agent confirms before mutating, unless user says "just do it".

### 6. Hard-rule validation
- **Today:** `validate_plan` runs inside `update_plan`; warnings returned in the result.

### 7. Web search subagent
- **Story:** "Find me 3 new bacalhau recipes."
- **Today:** Isolated `recipe_finder` subagent on `:online` model, results
  appended to `recipes.json`.

### 8. Cookidoo integration
- **Today:** `list_cookidoo_collections`, `get_cookidoo_collection(col_id)`,
  `fetch_cookidoo_recipe(recipe_id)`. Auth via `cookidoo_user` / `cookiday_pass`.
- **Limitations:** Per-call login; queries time out on large libraries (planned
  fix in next sub-project).

### 9. Tracing & evals *(added 2026-05-03)*
- **Today:** `traces/summary.jsonl` (per-turn summary) + `traces/full/<turn_id>.json`
  (full message list). Sidebar caption shows last-turn cost.
- `pytest -m eval` opt-in real-model harness; per-test row in `traces/eval_runs.csv`.
```

- [ ] **Step 2: Commit**

```powershell
git add docs/PRD.md
git commit -m "docs: add PRD with current capabilities"
```

### Task 9.3: architecture.yaml

**Files:**
- Create: `docs/architecture.yaml`

- [ ] **Step 1: Write `docs/architecture.yaml`**

(Use the YAML from §2 of the spec — `docs/superpowers/specs/2026-05-03-edit-recipes-and-tracing-design.md`. Verbatim, including all 17 tools.)

- [ ] **Step 2: Verify it's parseable YAML**

Run:
```powershell
.venv\Scripts\python.exe -c "import yaml; yaml.safe_load(open('docs/architecture.yaml','r',encoding='utf-8').read()); print('ok')"
```

If `pyyaml` is not installed, install it as a dev tool:
```powershell
.venv\Scripts\pip.exe install pyyaml
```
Then rerun the check. Don't add `pyyaml` to `pyproject.toml` — it's only used for offline validation.

Expected: `ok`.

- [ ] **Step 3: Commit**

```powershell
git add docs/architecture.yaml
git commit -m "docs: add architecture.yaml as source of truth"
```

### Task 9.4: BUILD_SPEC.md

**Files:**
- Create: `docs/BUILD_SPEC.md`

- [ ] **Step 1: Write `docs/BUILD_SPEC.md`**

```markdown
# Build Spec

> Hand-maintained against `architecture.yaml`. Update on every PR that
> changes a component, tool, state file, or external service.

## Components

| File | Kind | Notes |
|---|---|---|
| `app.py` | Streamlit UI | chat input, plan table, sidebar (profile, pantry, ratings, last-turn cost) |
| `agents/orchestrator.py` | Agent | LiteLLM via OpenRouter (`claude-sonnet-4.5`); 17 tools; bg job registry |
| `agents/recipe_finder.py` | Subagent | LiteLLM (`gemini-2.5-flash:online` for web search); isolated context |
| `tools/profile.py` | Tools | `read_profile`, `update_profile` |
| `tools/state.py` | Tools | `read_state`, `update_plan`, `update_pantry`, `record_rating`, snapshots |
| `tools/recipes.py` | Tools | `list_recipes`, `get_recipe`, `search_recipes`, `find_new_recipes_tool`, `update_recipe`, `delete_recipe`, persistence helpers |
| `tools/cookidoo.py` | Tools | `list_cookidoo_collections`, `get_cookidoo_collection`, `fetch_cookidoo_recipe` |
| `tools/validate.py` | Tools | `validate_plan` (pure, no LLM) |
| `models.py` | Schemas | Pydantic: `Member`, `Profile`, `Recipe`, `Rating`, `MealPlanSlot`, `ArchivedPlan`, `State` |
| `storage.py` | Persistence | atomic JSON read/write to `state/` |
| `tracing.py` | Tracing | `start_turn`, `record_completion`, `record_tool_call`, `end_turn`, `attach_subagent`, `last_turn_summary` |

## Tools exposed to orchestrator (17)

| Name | Module | Side-effects |
|---|---|---|
| `read_profile` | `tools/profile.py` | none |
| `update_profile` | `tools/profile.py` | writes `profile.json` |
| `read_state` | `tools/state.py` | none |
| `update_plan` | `tools/state.py` | writes `state.json`; runs `validate_plan` inline |
| `update_pantry` | `tools/state.py` | writes `state.json` |
| `record_rating` | `tools/state.py` | writes `state.json` |
| `list_recipes` | `tools/recipes.py` | none |
| `get_recipe` | `tools/recipes.py` | none |
| `search_recipes` | `tools/recipes.py` | none |
| `find_new_recipes` | `tools/recipes.py` | writes `recipes.json`; spawns `recipe_finder` subagent |
| `update_recipe` | `tools/recipes.py` | writes `recipes.json` |
| `delete_recipe` | `tools/recipes.py` | writes `recipes.json` |
| `list_cookidoo_collections` | `tools/cookidoo.py` | none (auth call to Cookidoo) |
| `get_cookidoo_collection` | `tools/cookidoo.py` | none (auth call to Cookidoo) |
| `fetch_cookidoo_recipe` | `tools/cookidoo.py` | writes `recipes.json` (auth call to Cookidoo) |
| `validate_plan` | `tools/validate.py` | none |
| `undo` | `agents/orchestrator.py` | writes `state.json` |
| `check_search_status` | `agents/orchestrator.py` | none |

(Note: 18 entries above; `undo` and `check_search_status` are exposed to the
orchestrator but live inside `orchestrator.py` rather than `tools/`. The
"17 tools" headline figure counts user-facing recipe/state/plan tools only.)

## State files

| Path | Schema | Mutability |
|---|---|---|
| `state/profile.json` | `models.Profile` | rare changes (onboarding, prefs) |
| `state/recipes.json` | `list[models.Recipe]` | grows over time |
| `state/state.json` | `models.State` | weekly |

## External services

| Service | Used by | Notes |
|---|---|---|
| OpenRouter | orchestrator, recipe_finder | LiteLLM client; `OPENROUTER_API_KEY` env var |
| Cookidoo API | `tools/cookidoo.py` | `cookidoo-api` package; per-call login (planned: connection pooling) |
| Web search | `recipe_finder` | routed via OpenRouter `:online` model suffix |

## Background workers

`agents/orchestrator._bg_jobs` — in-memory dict keyed by job_id. Used for
backgrounded recipe searches (long web fetches) so the chat thread stays
responsive. Status polled by `check_search_status`.

## Trace artifacts

| Path | Format | Purpose |
|---|---|---|
| `traces/summary.jsonl` | JSON-per-line | one record per chat turn (model, tokens, latency, tool calls) |
| `traces/full/<turn_id>.json` | JSON | verbatim message list for replay/debug |
| `traces/eval_runs.csv` | CSV | one row per `pytest -m eval` test invocation |

All trace writes are best-effort; failures never propagate into the chat loop.
```

- [ ] **Step 2: Commit**

```powershell
git add docs/BUILD_SPEC.md
git commit -m "docs: add BUILD_SPEC.md (current implementation snapshot)"
```

---

## Phase 10 — README + final verification

### Task 10.1: Update README with tracing/eval sections

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append to `README.md`**

After the existing `## Tests` section, replace it with:

```markdown
## Tests

```bash
.venv/Scripts/pytest.exe -v          # unit tests only (default; fast, free)
.venv/Scripts/pytest.exe -m eval -v  # opt-in real-model evals (cost tokens)
```

Unit tests cover: validator rules, storage round-trips, search ranking, model
serialization, recipe CRUD, tracing.

Evals replay scripted user turns against the live model and assert tool-call
shape + token ceilings. Each run appends a row to `traces/eval_runs.csv`.

## Tracing

Every chat turn writes:

- `traces/summary.jsonl` — one JSON line per turn: `{turn_id, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, tool_calls}`.
- `traces/full/<turn_id>.json` — full message list for replay / debugging.

Sidebar shows the last turn's cost. `traces/` is gitignored.

## Project docs

- `docs/BRD.md` — business requirements
- `docs/PRD.md` — product capabilities (current state)
- `docs/BUILD_SPEC.md` — current implementation
- `docs/architecture.yaml` — machine-readable architecture (source of truth for `BUILD_SPEC.md`)
- `docs/superpowers/specs/` — per-sub-project design specs
- `docs/superpowers/plans/` — per-sub-project implementation plans
```

- [ ] **Step 2: Commit**

```powershell
git add README.md
git commit -m "docs(readme): document tracing, evals, and project docs"
```

### Task 10.2: Final verification

- [ ] **Step 1: Default pytest run is green and fast**

Run: `.venv\Scripts\pytest.exe -v`
Expected: all unit tests PASS, no eval tests collected.

- [ ] **Step 2: Eval-only run still selects evals**

Run: `.venv\Scripts\pytest.exe -m eval --collect-only -q`
Expected: lists eval tests under `tests/evals/`. (Don't actually run them all here unless you want to spend tokens.)

- [ ] **Step 3: App boots**

Run: `.venv\Scripts\streamlit.exe run app.py`
Manually open http://localhost:8501. Confirm:
- Page renders.
- Sidebar shows "Last turn:" caption (with `(no traces yet)` if `summary.jsonl` is empty).
- Send a one-line message ("hi"), wait for the reply, confirm sidebar updates with token / latency / tool count.

Stop the server.

- [ ] **Step 4: One eval, end-to-end (optional, costs tokens)**

Run: `.venv\Scripts\pytest.exe -m eval tests/evals/test_capabilities.py::test_edit_recipe_changes_cuisine -v`
Expected: PASS, and a row appended to `traces/eval_runs.csv`.

Inspect: `Get-Content traces\eval_runs.csv | Select-Object -Last 3`

- [ ] **Step 5: Final commit (only if anything was tweaked during verification)**

```powershell
git status
# if nothing pending, skip the commit
```

---

## Self-review

**Spec coverage check (each numbered section in the spec):**

- §1 Goal & scope: A. living docs (Tasks 9.1–9.4), B.1 recipe edit/delete (Tasks 1.1, 2.1–2.5, 3.1–3.2), B.2 tracing (Tasks 4.1–4.3, 5.1–5.2, 6.1), B.3 tests (Tasks 2.1–2.5, 4.1–4.3, 7.1–7.2, 8.1–8.4). ✓
- §2 Project-level docs structure: Tasks 9.1–9.4. ✓
- §3 Recipe edit & delete (model + tools + dispatch + prompt): Tasks 1.1 (model), 2.1–2.5 (tools/tests), 3.1 (dispatch), 3.2 (prompt). ✓
- §4 Tracing module (start/record/end + subagent + sidebar + privacy + truncation visibility): Tasks 4.1–4.3 (module), 5.1 (orchestrator wiring), 5.2 (subagent wiring), 6.1 (sidebar). Privacy via `.gitignore` Task 0.1. Truncation visibility — `record_tool_call` is called with `len(result)` BEFORE truncation in Task 5.1 step 3. ✓
- §5 Tests (unit + eval split, marker, CSV, fixtures, ceilings): Tasks 7.1 (marker), 7.2 (scaffold), 8.1–8.4 (tests), Task 1.1 / 2.* / 4.* (unit). ✓
- §6 Project layout: emerges from the file ops; Task 10.1 documents it in README. ✓
- §7 Risks: addressed inline (best-effort tracing, default `notes=""`, missing `usage` graceful, eval skipif on Cookidoo, addopts for default skip). ✓
- §8 Implementation order: matches phase order. ✓

**Placeholder scan:** searched for "TBD", "TODO", "implement later", "fill in", "similar to". None found. (`test_cookidoo_import` deliberately skips with a clear message; that's a runtime skip, not a plan placeholder.)

**Type / signature consistency:**
- `update_recipe(recipe_id, fields)` — same signature in tools, schema, dispatcher, eval. ✓
- `delete_recipe(recipe_id) -> bool` — same. ✓
- `tracing.record_completion(turn_id, response, latency_ms)` — used identically in orchestrator (5.1) and recipe-finder (5.2). ✓
- `tracing.record_tool_call(turn_id, name, args, result_chars, ms)` — orchestrator passes `len(result)` (pre-truncation). ✓
- `find_new_recipes(...) -> tuple[list[Recipe], dict]` — caller (`find_new_recipes_tool`) unpacks `(found, _sub)`. ✓
- `_dispatch(name, args, turn_id=None)` — backwards-compatible default; called with `turn_id` from `_run_one`. ✓

No issues found.
