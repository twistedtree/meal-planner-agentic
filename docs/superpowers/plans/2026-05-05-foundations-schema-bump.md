# Foundations: household_id + State Schema Bump — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bump `Profile` and `State` schemas to add `household_id` (default `"default"`), promote `pantry: list[str]` to `list[PantryItem]` with `{name, quantity?, expiry_at?}`, and add `tonight_history: list[OneOffMeal]`. Backwards-compatible loaders coerce existing on-disk files. `update_pantry` tool accepts heterogeneous `add` input. No user-visible behaviour change.

**Architecture:** Pure schema bump. Two new Pydantic models (`PantryItem`, `OneOffMeal`) added to `models.py`. `State.pantry` gets a `field_validator(mode="before")` that coerces bare strings to `{"name": s}` dicts so legacy files load unchanged. `tools/state.update_pantry` normalises every `add` entry to `PantryItem` and dedupes by `name.lower().strip()`, with later writes overwriting non-None `quantity` / `expiry_at`. Orchestrator's `update_pantry` tool schema accepts `anyOf: string | object`. `_state_summary` renders pantry as `name (q, exp d)` when those fields are set. `app.py` sidebar iterates `PantryItem.name`.

**Tech Stack:** Python 3.12, pydantic 2 (`field_validator(mode="before")`), LiteLLM (OpenRouter), Streamlit, pytest. No new runtime dependencies.

**Working directory:** the app root (`05-projects/meal-planner-agentic`). All file paths below are relative to that directory.

**Spec reference:** `docs/superpowers/specs/2026-05-05-foundations-schema-bump-design.md`.

---

## Phase 0 — Pre-flight

### Task 0.1: Confirm the repo is clean and tests are green

- [ ] **Step 1: Confirm working tree state**

Run: `git status`
Expected: branch `main`. Record any prior unrelated changes; we will only commit files this plan touches.

- [ ] **Step 2: Verify pytest currently passes**

Run (Windows): `.venv\Scripts\pytest.exe -v`
Expected: green for the default (non-eval) test selection.

If any test is red on `main`, stop and report. Do not paper over a pre-existing red.

- [ ] **Step 3: Capture a baseline state file for round-trip checks**

Run:
```powershell
Copy-Item state\profile.json state\.profile.pre-2026-05-05.json -ErrorAction SilentlyContinue
Copy-Item state\state.json state\.state.pre-2026-05-05.json -ErrorAction SilentlyContinue
```

These backup copies are gitignored (under `state/`) and let you eyeball "before / after" if anything looks off. Delete them once the rollout is confirmed.

---

## Phase 1 — New Pydantic models

### Task 1.1: Add `PantryItem` and `OneOffMeal` to `models.py`

**Files:**
- Modify: `models.py`
- Test: `tests/test_models.py` (existing) — add cases

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
def test_pantry_item_minimal():
    from models import PantryItem
    p = PantryItem(name="rice")
    assert p.name == "rice"
    assert p.quantity is None
    assert p.expiry_at is None


def test_pantry_item_full():
    from datetime import date
    from models import PantryItem
    p = PantryItem(name="salmon", quantity="280g", expiry_at=date(2026, 5, 7))
    assert p.quantity == "280g"
    assert p.expiry_at == date(2026, 5, 7)


def test_one_off_meal_minimal():
    from datetime import datetime
    from models import OneOffMeal
    m = OneOffMeal(recipe_title="Pasta al Pomodoro", cooked_at=datetime(2026, 5, 5, 19, 0))
    assert m.members == []
    assert m.time_min is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest.exe tests/test_models.py::test_pantry_item_minimal -v`
Expected: FAIL with `ImportError` (the class doesn't exist yet).

- [ ] **Step 3: Add the models**

Edit `models.py`. After the existing imports and before `class Member`, the file already has `from datetime import datetime, date`. Add `field_validator` to the pydantic import. Then, just above `class Member`, add:

```python
class PantryItem(BaseModel):
    name: str
    quantity: str | None = None
    expiry_at: date | None = None


class OneOffMeal(BaseModel):
    recipe_title: str
    cooked_at: datetime
    members: list[str] = Field(default_factory=list)
    time_min: int | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest.exe tests/test_models.py -v`
Expected: new tests PASS, all pre-existing tests still PASS.

- [ ] **Step 5: Commit**

```powershell
git add models.py tests/test_models.py
git commit -m "feat(models): add PantryItem and OneOffMeal"
```

---

## Phase 2 — `Profile.household_id`

### Task 2.1: Add `household_id` to `Profile` with default + legacy load

**Files:**
- Modify: `models.py:12-18` (`class Profile`)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
def test_profile_defaults_household_id():
    from models import Profile, Member
    p = Profile(
        household_size=1,
        members=[Member(name="Miguel", is_adult=True)],
    )
    assert p.household_id == "default"


def test_profile_loads_legacy_without_household_id():
    """A profile.json written before this schema bump must load unchanged."""
    import json
    from models import Profile
    legacy = json.dumps({
        "household_size": 4,
        "members": [
            {"name": "Miguel", "is_adult": True, "dislikes": []},
            {"name": "K", "is_adult": True, "dislikes": []},
        ],
        "household_dislikes": [],
        "dietary_rules": [],
        "preferred_cuisines": [],
        "notes": "",
    })
    p = Profile.model_validate_json(legacy)
    assert p.household_id == "default"
    assert p.household_size == 4


def test_profile_round_trips_household_id():
    from models import Profile, Member
    p = Profile(
        household_id="m-family",
        household_size=2,
        members=[Member(name="A", is_adult=True), Member(name="B", is_adult=True)],
    )
    j = p.model_dump_json()
    p2 = Profile.model_validate_json(j)
    assert p2.household_id == "m-family"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest.exe tests/test_models.py::test_profile_defaults_household_id -v`
Expected: FAIL with `AttributeError` or `ValidationError`.

- [ ] **Step 3: Add the field**

Edit `models.py`. In `class Profile`, add as the first field (above `household_size`):

```python
    household_id: str = "default"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest.exe tests/test_models.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add models.py tests/test_models.py
git commit -m "feat(models): add Profile.household_id with default"
```

---

## Phase 3 — `State.household_id` + `State.tonight_history`

### Task 3.1: Add `household_id` and `tonight_history` to `State`

**Files:**
- Modify: `models.py:59-66` (`class State`)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
def test_state_defaults_household_id_and_tonight_history():
    from datetime import datetime
    from models import State
    s = State(last_updated=datetime(2026, 5, 5, 19, 0))
    assert s.household_id == "default"
    assert s.tonight_history == []


def test_state_loads_legacy_without_new_fields():
    """A state.json from before this schema bump must load unchanged."""
    import json
    from models import State
    legacy = json.dumps({
        "meal_plan": [],
        "week_of": None,
        "plan_history": [],
        "pantry": [],
        "ratings": [],
        "last_updated": "2026-05-04T12:00:00",
    })
    s = State.model_validate_json(legacy)
    assert s.household_id == "default"
    assert s.tonight_history == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest.exe tests/test_models.py::test_state_defaults_household_id_and_tonight_history -v`
Expected: FAIL.

- [ ] **Step 3: Add the fields**

Edit `models.py`. In `class State`, add `household_id` as the first field (above `meal_plan`) and `tonight_history` after `ratings`:

```python
class State(BaseModel):
    household_id: str = "default"                                    # NEW
    meal_plan: list[MealPlanSlot] = Field(default_factory=list)
    week_of: date | None = None
    plan_history: list[ArchivedPlan] = Field(default_factory=list)
    pantry: list[PantryItem] = Field(default_factory=list)           # type changed in Task 4.1
    ratings: list[Rating] = Field(default_factory=list)
    tonight_history: list[OneOffMeal] = Field(default_factory=list)  # NEW
    last_updated: datetime
```

NOTE: don't change `pantry` to `list[PantryItem]` yet — that change ships with the validator in Phase 4 and would break this task's tests if applied alone. For now leave `pantry: list[str] = Field(default_factory=list)` as-is.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest.exe tests/test_models.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add models.py tests/test_models.py
git commit -m "feat(models): add State.household_id and State.tonight_history"
```

---

## Phase 4 — Pantry coercion

### Task 4.1: Add the legacy-pantry validator and switch the field type

**Files:**
- Modify: `models.py` (`class State`)
- Test: `tests/test_state_schema_2026_05_05.py` (NEW)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_state_schema_2026_05_05.py`:

```python
"""Schema-bump tests for the 2026-05-05 foundations sub-project."""
import json
from datetime import datetime, date
from pathlib import Path

import storage
import tools.state as state_mod
from models import State, PantryItem


def _write_state(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "state.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_state_loads_legacy_pantry_strings(tmp_path, monkeypatch):
    """Bare-string pantry entries from older state.json files must load."""
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    _write_state(tmp_path, {
        "meal_plan": [], "week_of": None, "plan_history": [],
        "pantry": ["rice", "salmon", "tinned tomatoes"],
        "ratings": [], "last_updated": "2026-05-04T12:00:00",
    })
    s = state_mod.read_state()
    assert all(isinstance(p, PantryItem) for p in s.pantry)
    assert [p.name for p in s.pantry] == ["rice", "salmon", "tinned tomatoes"]
    assert all(p.quantity is None and p.expiry_at is None for p in s.pantry)


def test_state_loads_mixed_pantry(tmp_path, monkeypatch):
    """Mixed string + dict pantry entries must load."""
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    _write_state(tmp_path, {
        "meal_plan": [], "week_of": None, "plan_history": [],
        "pantry": [
            "rice",
            {"name": "salmon", "quantity": "280g", "expiry_at": "2026-05-07"},
        ],
        "ratings": [], "last_updated": "2026-05-04T12:00:00",
    })
    s = state_mod.read_state()
    assert s.pantry[0] == PantryItem(name="rice")
    assert s.pantry[1] == PantryItem(
        name="salmon", quantity="280g", expiry_at=date(2026, 5, 7),
    )


def test_pantry_round_trip_normalises_to_dicts(tmp_path, monkeypatch):
    """Legacy load → save → reload should produce dict-shaped on-disk pantry."""
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    _write_state(tmp_path, {
        "meal_plan": [], "week_of": None, "plan_history": [],
        "pantry": ["rice"],
        "ratings": [], "last_updated": "2026-05-04T12:00:00",
    })
    s = state_mod.read_state()
    storage.save_json("state.json", s)

    raw = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert raw["pantry"] == [
        {"name": "rice", "quantity": None, "expiry_at": None},
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest.exe tests/test_state_schema_2026_05_05.py -v`
Expected: FAIL — `pantry` is still typed `list[str]`, so the dict entries blow up validation.

- [ ] **Step 3: Switch the field type and add the validator**

Edit `models.py`. Update the `field_validator` import:

```python
from pydantic import BaseModel, Field, field_validator
```

In `class State`, change:

```python
    pantry: list[str] = Field(default_factory=list)
```

to:

```python
    pantry: list[PantryItem] = Field(default_factory=list)
```

Then, immediately after `last_updated: datetime` (still inside `class State`), add the coercion validator:

```python
    @field_validator("pantry", mode="before")
    @classmethod
    def _coerce_legacy_pantry(cls, v):
        """Coerce bare-string pantry entries to PantryItem dicts."""
        if not isinstance(v, list):
            return v
        return [
            {"name": x} if isinstance(x, str) else x
            for x in v
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest.exe tests/test_state_schema_2026_05_05.py -v`
Expected: PASS.

Run: `.venv\Scripts\pytest.exe -v`
Expected: existing tests that read `s.pantry` may now break if they assume `list[str]`. Move on to Phase 5; existing-test fixes happen in Task 8.2.

- [ ] **Step 5: Commit**

```powershell
git add models.py tests/test_state_schema_2026_05_05.py
git commit -m "feat(models): coerce legacy pantry strings to PantryItem"
```

---

## Phase 5 — `update_pantry` tool

### Task 5.1: Accept heterogeneous `add` and dedupe by name

**Files:**
- Modify: `tools/state.py:32-43` (`update_pantry`)
- Test: `tests/test_state_schema_2026_05_05.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state_schema_2026_05_05.py`:

```python
import storage
import tools.state as state_mod
from models import PantryItem


def _fresh_state(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)


def test_update_pantry_accepts_bare_string(tmp_path, monkeypatch):
    _fresh_state(tmp_path, monkeypatch)
    s = state_mod.update_pantry(add=["rice"])
    assert s.pantry == [PantryItem(name="rice")]


def test_update_pantry_accepts_dict(tmp_path, monkeypatch):
    _fresh_state(tmp_path, monkeypatch)
    s = state_mod.update_pantry(add=[{
        "name": "salmon", "quantity": "280g", "expiry_at": "2026-05-07",
    }])
    assert s.pantry[0].name == "salmon"
    assert s.pantry[0].quantity == "280g"
    assert s.pantry[0].expiry_at == date(2026, 5, 7)


def test_update_pantry_dedupe_overwrites_quantity(tmp_path, monkeypatch):
    _fresh_state(tmp_path, monkeypatch)
    state_mod.update_pantry(add=["rice"])
    s = state_mod.update_pantry(add=[{"name": "rice", "quantity": "1 bag"}])
    assert len(s.pantry) == 1
    assert s.pantry[0].quantity == "1 bag"


def test_update_pantry_dedupe_keeps_later_expiry(tmp_path, monkeypatch):
    _fresh_state(tmp_path, monkeypatch)
    state_mod.update_pantry(add=[{"name": "salmon", "expiry_at": "2026-05-07"}])
    s = state_mod.update_pantry(add=[{"name": "salmon", "expiry_at": "2026-05-09"}])
    assert len(s.pantry) == 1
    assert s.pantry[0].expiry_at == date(2026, 5, 9)


def test_update_pantry_remove_case_insensitive(tmp_path, monkeypatch):
    _fresh_state(tmp_path, monkeypatch)
    state_mod.update_pantry(add=["Salmon"])
    s = state_mod.update_pantry(remove=["salmon"])
    assert s.pantry == []


def test_update_pantry_dedupe_does_not_clear_quantity(tmp_path, monkeypatch):
    """Adding a bare name when an item with quantity already exists must not wipe quantity."""
    _fresh_state(tmp_path, monkeypatch)
    state_mod.update_pantry(add=[{"name": "salmon", "quantity": "280g"}])
    s = state_mod.update_pantry(add=["salmon"])
    assert len(s.pantry) == 1
    assert s.pantry[0].quantity == "280g"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\pytest.exe tests/test_state_schema_2026_05_05.py -v`
Expected: FAIL — `update_pantry` doesn't accept dicts yet.

- [ ] **Step 3: Implement the new `update_pantry`**

Edit `tools/state.py`. Replace the existing `update_pantry` (lines ~32-43) with:

```python
def update_pantry(
    add: list[str | dict] | None = None,
    remove: list[str] | None = None,
) -> State:
    """Apply a diff to the pantry.

    `add` accepts bare strings or {name, quantity?, expiry_at?} dicts.
    Dedupe key is name.lower().strip(). On collision, non-None quantity /
    expiry_at from the new entry overwrite the existing values; bare-name
    re-adds preserve existing quantity / expiry_at.
    `remove` is a list of names; case-insensitive exact match.
    """
    s = read_state()
    by_name: dict[str, PantryItem] = {
        p.name.lower().strip(): p for p in s.pantry
    }

    for entry in (add or []):
        if isinstance(entry, str):
            new = PantryItem(name=entry.strip())
        else:
            new = PantryItem.model_validate(entry)
        key = new.name.lower().strip()
        if key in by_name:
            existing = by_name[key]
            merged = existing.model_copy(update={
                "quantity": new.quantity if new.quantity is not None else existing.quantity,
                "expiry_at": new.expiry_at if new.expiry_at is not None else existing.expiry_at,
            })
            by_name[key] = merged
        else:
            by_name[key] = new

    for name in (remove or []):
        by_name.pop(name.lower().strip(), None)

    s.pantry = sorted(by_name.values(), key=lambda p: p.name.lower())
    s.last_updated = _now()
    save_json("state.json", s)
    return s
```

Add `from models import State, MealPlanSlot, Rating, ArchivedPlan, PantryItem` at the top of the file (extend the existing import).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\pytest.exe tests/test_state_schema_2026_05_05.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/state.py tests/test_state_schema_2026_05_05.py
git commit -m "feat(state): update_pantry accepts dict entries with quantity/expiry"
```

---

## Phase 6 — Orchestrator: tool schema + state summary + prompt

### Task 6.1: Update the `update_pantry` tool schema

**Files:**
- Modify: `agents/orchestrator.py` (the `_tool("update_pantry", ...)` block, ~lines 124-133)

- [ ] **Step 1: Replace the schema**

Find the existing `_tool("update_pantry", ...)` definition. Replace its parameters block with:

```python
    _tool("update_pantry",
          "Add or remove perishables in the pantry. Items can be bare names or "
          "objects with optional quantity (free text, e.g. '250g') and expiry_at "
          "(ISO date YYYY-MM-DD).",
          {
              "type": "object",
              "properties": {
                  "add": {
                      "type": "array",
                      "items": {
                          "anyOf": [
                              {"type": "string"},
                              {
                                  "type": "object",
                                  "properties": {
                                      "name":      {"type": "string"},
                                      "quantity":  {"type": ["string", "null"]},
                                      "expiry_at": {
                                          "type": ["string", "null"],
                                          "description": "ISO date YYYY-MM-DD",
                                      },
                                  },
                                  "required": ["name"],
                              },
                          ],
                      },
                  },
                  "remove": {"type": "array", "items": {"type": "string"}},
              },
              "required": [],
          }),
```

The `_dispatch` branch for `update_pantry` already passes `args.get("add", [])` straight through — no change needed there.

- [ ] **Step 2: Smoke test the schema with a manual dispatch**

Run a small Python REPL or one-off script:

```powershell
.venv\Scripts\python.exe -c "
import json
from agents.orchestrator import _dispatch
import storage; storage.STATE_DIR.mkdir(exist_ok=True)
print(_dispatch('update_pantry', {'add': ['rice', {'name': 'salmon', 'quantity': '280g', 'expiry_at': '2026-05-07'}]}))
"
```

Expected: prints the resulting `State` JSON with both pantry items.

- [ ] **Step 3: Commit**

```powershell
git add agents/orchestrator.py
git commit -m "feat(orchestrator): update_pantry tool accepts dict items"
```

---

### Task 6.2: Update `_state_summary` to render the new pantry shape

**Files:**
- Modify: `agents/orchestrator.py` (`_state_summary`, ~lines 355-376)
- Test: `tests/test_state_schema_2026_05_05.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_state_schema_2026_05_05.py`:

```python
def test_state_summary_renders_pantry_shapes(tmp_path, monkeypatch):
    """Pantry rendering: bare name, name + qty, name + expiry, name + both."""
    monkeypatch.setattr(storage, "STATE_DIR", tmp_path)
    state_mod.update_pantry(add=[
        "rice",
        {"name": "salmon", "quantity": "280g", "expiry_at": "2026-05-07"},
        {"name": "lemons", "quantity": "x4"},
        {"name": "yoghurt", "expiry_at": "2026-05-09"},
    ])

    from agents.orchestrator import _state_summary
    summary = _state_summary()
    assert "rice" in summary
    assert "salmon (280g, exp 2026-05-07)" in summary
    assert "lemons (x4)" in summary
    assert "yoghurt (exp 2026-05-09)" in summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\pytest.exe tests/test_state_schema_2026_05_05.py::test_state_summary_renders_pantry_shapes -v`
Expected: FAIL — current `_state_summary` joins `s.pantry` as if it were strings.

- [ ] **Step 3: Implement the new rendering**

Edit `agents/orchestrator.py`. Inside `_state_summary`, replace:

```python
    pantry = ", ".join(s.pantry) if s.pantry else "(empty)"
```

with:

```python
    def _render_item(p) -> str:
        bits = []
        if p.quantity is not None:
            bits.append(p.quantity)
        if p.expiry_at is not None:
            bits.append(f"exp {p.expiry_at.isoformat()}")
        return f"{p.name} ({', '.join(bits)})" if bits else p.name

    pantry = ", ".join(_render_item(p) for p in s.pantry) if s.pantry else "(empty)"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\pytest.exe tests/test_state_schema_2026_05_05.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add agents/orchestrator.py tests/test_state_schema_2026_05_05.py
git commit -m "feat(orchestrator): render pantry items with quantity and expiry"
```

---

### Task 6.3: Add the pantry-shape note to the system prompt

**Files:**
- Modify: `agents/prompts.py` (`ORCHESTRATOR_SYSTEM_PROMPT`)

- [ ] **Step 1: Add the note**

Edit `agents/prompts.py`. In the existing `TOOL EFFICIENCY` section of `ORCHESTRATOR_SYSTEM_PROMPT`, after the bullet about `validate_plan` running automatically, insert:

```
- The pantry is a list of items, each with a name plus an optional free-text
  quantity (e.g. "250g", "1 bag") and an optional expiry date (ISO YYYY-MM-DD).
  When the user mentions a quantity or expiry date, pass it through update_pantry
  as a dict; otherwise a bare name string is fine.
```

- [ ] **Step 2: Commit**

```powershell
git add agents/prompts.py
git commit -m "feat(prompts): document pantry item shape for update_pantry"
```

---

## Phase 7 — Streamlit UI

### Task 7.1: Iterate `PantryItem.name` in the sidebar

**Files:**
- Modify: `app.py` (sidebar pantry render, around line 70)

- [ ] **Step 1: Replace the pantry render**

Edit `app.py`. Inside `_render_sidebar`, find:

```python
        st.subheader("Pantry")
        s = read_state()
        if s.pantry:
            st.write(" · ".join(s.pantry))
        else:
            st.caption("(empty)")
```

Replace the join line with:

```python
            st.write(" · ".join(p.name for p in s.pantry))
```

The expiry / quantity pills come in capability 11. For now, names only.

- [ ] **Step 2: Smoke test**

Run: `.venv\Scripts\streamlit.exe run app.py`
Open the app. Pantry sidebar should render whatever item names are in `state.json`.

- [ ] **Step 3: Commit**

```powershell
git add app.py
git commit -m "feat(ui): iterate PantryItem.name in sidebar pantry render"
```

---

## Phase 8 — Test cleanup and full run

### Task 8.1: Update existing tests that assume `pantry: list[str]`

**Files:**
- Modify (likely): `tests/test_state.py`, `tests/test_storage.py`, `tests/test_orchestrator.py`, `tests/evals/conftest.py`, eval fixtures

- [ ] **Step 1: Run the full unit suite and capture failures**

Run: `.venv\Scripts\pytest.exe -m "not eval" -v`
Expected: most pass; some assertions on `s.pantry` membership may fail.

- [ ] **Step 2: Fix each failure to read `p.name`**

For each failing assertion, change `assert "rice" in s.pantry` to `assert "rice" in (p.name for p in s.pantry)` or use `[p.name for p in s.pantry]` for list comparisons. Do not change test intent; just adjust to the new shape.

If any test set `s.pantry = ["rice"]` directly, change to `s.pantry = [PantryItem(name="rice")]`.

If `tests/evals/fixtures/*.json` includes a `state.json` fixture with bare-string pantry, leave the JSON shape alone — the validator coerces it.

- [ ] **Step 3: Re-run the unit suite until green**

Run: `.venv\Scripts\pytest.exe -m "not eval" -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```powershell
git add tests/
git commit -m "test: align existing tests with new pantry item shape"
```

---

### Task 8.2: Run the eval suite to confirm no regression

- [ ] **Step 1: Run evals (cost-aware: only the cheap capability tests first)**

Run: `.venv\Scripts\pytest.exe -m eval tests/evals/test_capabilities.py -v`
Expected: PASS. Pantry-related tool sequences should still work; rendering changes shouldn't trip token ceilings (the schema bump is invisible at the per-turn token level).

- [ ] **Step 2: Run the full workflow evals**

Run: `.venv\Scripts\pytest.exe -m eval tests/evals/test_workflows.py -v`
Expected: PASS. If any fails on a token ceiling, check whether the new pantry rendering grew the prompt. Acceptable drift is <5%; if larger, raise the ceiling and note it in the commit message.

- [ ] **Step 3: Commit (if any ceilings adjusted)**

```powershell
git add tests/evals/
git commit -m "test(evals): adjust ceilings for new pantry rendering (if needed)"
```

If no ceilings changed, skip this step.

---

## Phase 9 — Documentation updates

### Task 9.1: Update `architecture.yaml`: foundations is built

**Files:**
- Modify: `../docs/meal-planner-agentic/architecture.yaml`

- [ ] **Step 1: Move foundations from planned to current**

Edit the architecture file at `../docs/meal-planner-agentic/architecture.yaml` (relative to this app root, this is `C:\Users\migst\personal-kb\05-projects\docs\meal-planner-agentic\architecture.yaml`).

Two changes:

1. **Remove** the `planned_state_schema_changes` block (it is now built). Replace with a comment noting the build date:
   ```yaml
   # State schema bumped 2026-05-05 (see superpowers/specs/2026-05-05-foundations-schema-bump-design.md)
   ```

2. **Update** `state_files`:
   ```yaml
   state_files:
     - path: state/profile.json
       schema: models.Profile          # includes household_id (default "default")
     - path: state/recipes.json
       schema: list[models.Recipe]
     - path: state/state.json
       schema: models.State            # includes household_id, tonight_history, list[PantryItem] pantry
   ```

3. **Drop** `update_pantry_extended` from `planned_tools` (this sub-project shipped the extension).

- [ ] **Step 2: Commit**

```powershell
git add ..\docs\meal-planner-agentic\architecture.yaml
git commit -m "docs(arch): foundations schema bump shipped"
```

---

### Task 9.2: Update `BUILD_SPEC.md`

**Files:**
- Modify: `../docs/meal-planner-agentic/BUILD_SPEC.md`

- [ ] **Step 1: Update the Components and Tools tables**

In `BUILD_SPEC.md`, update the `Components` table to note `models.py` now includes `PantryItem` and `OneOffMeal`. Update the `Tools` table to note `update_pantry` accepts heterogeneous input.

In the `Planned components & tools` section, remove `update_pantry (extended)` from the planned tools (it shipped). Keep the rest of the planned section as-is.

In `Planned state schema changes`, mark the schema-bump rows as built by moving them out of the "Planned" table and noting "shipped 2026-05-05".

- [ ] **Step 2: Commit**

```powershell
git add ..\docs\meal-planner-agentic\BUILD_SPEC.md
git commit -m "docs(build-spec): foundations schema bump shipped"
```

---

### Task 9.3: Update `BRD.md`: foundations Done, capability 10 → in-progress

**Files:**
- Modify: `../docs/meal-planner-agentic/BRD.md`

- [ ] **Step 1: Move foundations from "in progress / next sub-project" to "Done"**

In `BRD.md`, under `### Done`, append (preserving the existing format):

```
- **`2026-05-05` — Foundations: household_id + state schema bump** ([spec](../../meal-planner-agentic/docs/superpowers/specs/2026-05-05-foundations-schema-bump-design.md), [plan](../../meal-planner-agentic/docs/superpowers/plans/2026-05-05-foundations-schema-bump.md)):
  Added `household_id="default"` to `Profile` and `State`; promoted `pantry` to `list[PantryItem]` with `{name, quantity?, expiry_at?}` shape; added `tonight_history`. Backwards-compatible loaders coerce existing on-disk files via Pydantic `field_validator(mode="before")`. `update_pantry` tool accepts heterogeneous input. No user-visible behaviour change. Unblocks capabilities 11 and 13.
```

- [ ] **Step 2: Update "In progress / next sub-project"**

Replace the current "In progress / next sub-project" foundations block with the next Tier-1 entry. Default: pull capability 1 (Calendar-aware planning) from the Planned list. Renumber the Planned list 1 → 5.

If you'd rather pick a different next slice, set this section accordingly. Either way, leave the `Independent bug fixes` section unchanged.

- [ ] **Step 3: Commit**

```powershell
git add ..\docs\meal-planner-agentic\BRD.md
git commit -m "docs(brd): foundations done; promote calendar to in-progress"
```

---

### Task 9.4: Update `PRD.md` cross-cap "Known gaps / deferred"

**Files:**
- Modify: `../docs/meal-planner-agentic/PRD.md`

- [ ] **Step 1: Mark schema-dependent capabilities as unblocked**

In the cross-cap "Known gaps / deferred" section, edit the lines for capability 11 and 13 to drop the "depends on foundations" caveat (foundations is now built). The capability text inside cap 11 / 13 itself does not need to change — the schema fields it references now actually exist.

- [ ] **Step 2: Commit**

```powershell
git add ..\docs\meal-planner-agentic\PRD.md
git commit -m "docs(prd): foundations shipped; caps 11 and 13 unblocked"
```

---

## Phase 10 — Final smoke

### Task 10.1: End-to-end manual smoke

- [ ] **Step 1: Run the app**

Run: `.venv\Scripts\streamlit.exe run app.py`

- [ ] **Step 2: Smoke the pantry flow**

In chat:

1. "Add rice, salmon (280g, expiring 2026-05-07), and lemons to the pantry."
2. Confirm the agent calls `update_pantry` with one bare name and two dicts (check the trace in `traces/full/<turn_id>.json` if needed).
3. Verify the sidebar pantry shows three items.
4. "Remove rice."
5. Verify the sidebar pantry shows two items.
6. Eyeball `state/state.json` — pantry items should be in dict shape on disk.

- [ ] **Step 3: Smoke a planning turn**

In chat: "Plan next week's dinners."
Verify `update_plan` runs and `validate_plan` warnings (if any) are surfaced. The plan flow is unchanged by this sub-project; this is just confirming we didn't break it.

- [ ] **Step 4: Final test sweep**

Run: `.venv\Scripts\pytest.exe -v`
Expected: all PASS.

Run: `.venv\Scripts\pytest.exe -m eval -v`
Expected: all PASS (within ceilings).

- [ ] **Step 5: Final cleanup**

Delete the pre-rollout backup files if you took them in Task 0.1:

```powershell
Remove-Item state\.profile.pre-2026-05-05.json -ErrorAction SilentlyContinue
Remove-Item state\.state.pre-2026-05-05.json -ErrorAction SilentlyContinue
```

---

## Out of scope (do NOT attempt in this plan)

- Capability 11 (pantry expiry-aware planning logic, default-expiry keyword table, sidebar expiry pills)
- Capability 13 (`plan_tonight` tool, `record_one_off_meal` tool, scoring)
- Capability 10 (calendar tool)
- Capability 12 (grocery list synthesis)
- Capability 14 (receipt-paste intake)
- Cookidoo timeout fix (independent bug-fix track in BRD)
- Multi-household scoping logic (the field is added; nothing reads it yet)
- Optional `scripts/migrate_state_schema_2026_05_05.py` (lazy loaders handle it; skipped per project decision)

---

## Risks during execution

- **`anyOf` rejected by upstream provider.** If `claude-sonnet-4.5` via OpenRouter rejects the `anyOf` shape on `update_pantry.add`, fall back to `{"type": "object"}` only and rely on the prompt note to make the agent always wrap bare names. Detection: a 400 error from the provider after Task 6.1.
- **Eval ceiling drift.** The new pantry rendering can grow the system prompt by ~5 to 25 chars per item. If any eval fails on token ceiling, raise ceiling by no more than 5% and note in commit. Larger drift means the rendering is wrong; investigate before bumping ceilings.
- **Stale fixture files in `tests/evals/fixtures/`.** Bare-string pantry fixtures load fine via the validator. No change required there.
- **Existing on-disk `state/state.json`.** First save after this rollout normalises pantry to dict shape. If you want files visibly normalised before the next save, bring back the optional migration script (it's documented in the spec).
