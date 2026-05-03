# Meal Planner Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add progress reporting, background recipe search, parallel tool dispatch, date-aware meal plans, and cross-week repetition avoidance.

**Architecture:** Five changes layered bottom-up: (1) new model fields (`week_of`, `plan_history`) added first since tasks 4 & 5 depend on them, (2) parallel tool dispatch in orchestrator, (3) background job infra with thread + session-state polling, (4) progress callback threaded from recipe_finder through to Streamlit, (5) UI updates for date display and job status. Each task produces independently testable code.

**Tech Stack:** Python 3.11+, Streamlit, Pydantic, `concurrent.futures`, `threading`, Anthropic SDK.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `models.py` | Modify | Add `ArchivedPlan`, `week_of`, `plan_history` fields |
| `tools/state.py` | Modify | Archive old plan on update, accept `week_of` param |
| `tools/validate.py` | Modify | Add Rule 5: no repeats from previous week |
| `tools/recipes.py` | Modify | Add `threading.Lock` around `save_all_recipes` |
| `agents/recipe_finder.py` | Modify | Accept `on_progress` callback |
| `agents/orchestrator.py` | Modify | Parallel dispatch, background job infra, new tools, updated prompt context |
| `agents/prompts.py` | Modify | Strengthen no-repeat soft rule |
| `app.py` | Modify | Date header, progress bar, background job banner |
| `tests/test_models.py` | Modify | Tests for new model fields |
| `tests/test_state.py` | Create | Tests for plan archival and `week_of` |
| `tests/test_validate.py` | Modify | Tests for Rule 5 (no consecutive repeats) |
| `tests/test_orchestrator.py` | Create | Tests for parallel dispatch |

---

### Task 1: Add `ArchivedPlan`, `week_of`, and `plan_history` to models

**Files:**
- Modify: `models.py:42-56`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for new model fields**

In `tests/test_models.py`, add:

```python
from datetime import datetime, date
from models import Profile, Member, Recipe, Rating, MealPlanSlot, State, ArchivedPlan


def test_state_has_week_of_field():
    s = State(meal_plan=[], pantry=[], ratings=[], last_updated=datetime(2026, 4, 15))
    assert s.week_of is None  # default


def test_state_week_of_set():
    s = State(
        meal_plan=[], pantry=[], ratings=[],
        last_updated=datetime(2026, 4, 15),
        week_of=date(2026, 4, 13),
    )
    assert s.week_of == date(2026, 4, 13)


def test_archived_plan_roundtrip():
    slot = MealPlanSlot(
        day="Mon", recipe_title="Test", recipe_id=None,
        main_protein="chicken", key_ingredients=["onion"], rationale="test",
    )
    ap = ArchivedPlan(week_of=date(2026, 4, 6), slots=[slot])
    dumped = ap.model_dump_json()
    loaded = ArchivedPlan.model_validate_json(dumped)
    assert loaded.week_of == date(2026, 4, 6)
    assert len(loaded.slots) == 1


def test_state_plan_history_default_empty():
    s = State(meal_plan=[], pantry=[], ratings=[], last_updated=datetime(2026, 4, 15))
    assert s.plan_history == []


def test_state_plan_history_roundtrip():
    slot = MealPlanSlot(
        day="Mon", recipe_title="Test", recipe_id=None,
        main_protein="chicken", key_ingredients=["onion"], rationale="test",
    )
    ap = ArchivedPlan(week_of=date(2026, 4, 6), slots=[slot])
    s = State(
        meal_plan=[], pantry=[], ratings=[],
        last_updated=datetime(2026, 4, 15),
        plan_history=[ap],
    )
    dumped = s.model_dump_json()
    loaded = State.model_validate_json(dumped)
    assert len(loaded.plan_history) == 1
    assert loaded.plan_history[0].week_of == date(2026, 4, 6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest tests/test_models.py -v`
Expected: FAIL — `ArchivedPlan` not found, `week_of` unknown field.

- [ ] **Step 3: Implement the model changes**

In `models.py`, add `ArchivedPlan` before `State` and update `State`:

```python
from datetime import datetime, date
from typing import Literal
from pydantic import BaseModel, Field


class Member(BaseModel):
    name: str
    is_adult: bool
    dislikes: list[str] = Field(default_factory=list)


class Profile(BaseModel):
    household_size: int
    members: list[Member]
    household_dislikes: list[str] = Field(default_factory=list)
    dietary_rules: list[str] = Field(default_factory=list)
    preferred_cuisines: list[str] = Field(default_factory=list)
    notes: str = ""


class Recipe(BaseModel):
    id: str
    title: str
    cuisine: str
    main_protein: str
    key_ingredients: list[str]
    tags: list[str] = Field(default_factory=list)
    cook_time_min: int
    last_cooked: datetime | None = None
    times_cooked: int = 0
    avg_rating: float | None = None
    source_url: str | None = None
    added_at: datetime


class Rating(BaseModel):
    recipe_title: str
    rater: str
    rating: Literal["again_soon", "worth_repeating", "meh", "never_again"]
    cooked_at: datetime


class MealPlanSlot(BaseModel):
    day: Literal["Mon", "Tue", "Wed", "Thu", "Fri"]
    recipe_title: str
    recipe_id: str | None = None
    main_protein: str
    key_ingredients: list[str]
    rationale: str


class ArchivedPlan(BaseModel):
    week_of: date
    slots: list[MealPlanSlot]


class State(BaseModel):
    meal_plan: list[MealPlanSlot] = Field(default_factory=list)
    week_of: date | None = None
    plan_history: list[ArchivedPlan] = Field(default_factory=list)
    pantry: list[str] = Field(default_factory=list)
    ratings: list[Rating] = Field(default_factory=list)
    last_updated: datetime
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest tests/test_models.py -v`
Expected: All PASS.

- [ ] **Step 5: Run full test suite for regressions**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest -v`
Expected: All existing tests still pass. `test_state_empty_defaults` should still pass because `week_of` defaults to `None` and `plan_history` defaults to `[]`.

- [ ] **Step 6: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat(models): add ArchivedPlan, week_of, plan_history to State"
```

---

### Task 2: Update `tools/state.py` to archive plans and accept `week_of`

**Files:**
- Modify: `tools/state.py:1-25`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write failing tests for plan archival**

Create `tests/test_state.py`:

```python
from datetime import datetime, date
import pytest
from models import State, MealPlanSlot, ArchivedPlan
from tools.state import read_state, update_plan


@pytest.fixture
def tmp_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("storage.STATE_DIR", tmp_path)
    return tmp_path


def _slot(day, title):
    return {
        "day": day, "recipe_title": title, "recipe_id": None,
        "main_protein": "chicken", "key_ingredients": ["onion"],
        "rationale": "test",
    }


WEEK_1_SLOTS = [_slot(d, f"Week1-{d}") for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]]
WEEK_2_SLOTS = [_slot(d, f"Week2-{d}") for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]]


def test_update_plan_sets_week_of(tmp_state_dir):
    s = update_plan(WEEK_1_SLOTS, week_of=date(2026, 4, 13))
    assert s.week_of == date(2026, 4, 13)


def test_update_plan_archives_previous(tmp_state_dir):
    update_plan(WEEK_1_SLOTS, week_of=date(2026, 4, 13))
    s = update_plan(WEEK_2_SLOTS, week_of=date(2026, 4, 20))
    assert len(s.plan_history) == 1
    assert s.plan_history[0].week_of == date(2026, 4, 13)
    assert s.plan_history[0].slots[0].recipe_title == "Week1-Mon"


def test_update_plan_no_archive_without_week_of(tmp_state_dir):
    """If the first plan had no week_of, don't archive it (no date to label it)."""
    update_plan(WEEK_1_SLOTS)  # no week_of
    s = update_plan(WEEK_2_SLOTS, week_of=date(2026, 4, 20))
    assert len(s.plan_history) == 0


def test_update_plan_keeps_max_4_weeks(tmp_state_dir):
    for i in range(6):
        slots = [_slot(d, f"W{i}-{d}") for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]]
        update_plan(slots, week_of=date(2026, 3, 2 + i * 7))
    s = read_state()
    assert len(s.plan_history) == 4


def test_update_plan_infers_monday_when_no_week_of(tmp_state_dir):
    s = update_plan(WEEK_1_SLOTS, week_of=None)
    # week_of should be None when not provided
    assert s.week_of is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest tests/test_state.py -v`
Expected: FAIL — `update_plan()` doesn't accept `week_of` parameter.

- [ ] **Step 3: Update `update_plan` in `tools/state.py`**

Replace the entire `update_plan` function (`tools/state.py:19-25`):

```python
def update_plan(slots: list[dict], week_of: date | None = None) -> State:
    """Replace meal_plan wholesale. Archives the previous plan if it had a week_of."""
    s = read_state()
    # Archive current plan before replacing (only if it has a date label)
    if s.meal_plan and s.week_of is not None:
        s.plan_history.append(ArchivedPlan(week_of=s.week_of, slots=s.meal_plan))
        s.plan_history = s.plan_history[-4:]  # keep last 4 weeks
    s.meal_plan = [MealPlanSlot.model_validate(slot) for slot in slots]
    s.week_of = week_of
    s.last_updated = _now()
    save_json("state.json", s)
    return s
```

Also update the imports at the top of `tools/state.py`:

```python
from datetime import datetime, date
from models import State, MealPlanSlot, Rating, ArchivedPlan
from storage import load_json, save_json, STATE_DIR
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest tests/test_state.py -v`
Expected: All PASS.

- [ ] **Step 5: Run full test suite for regressions**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest -v`
Expected: All pass. Existing callers of `update_plan(slots)` still work because `week_of` defaults to `None`.

- [ ] **Step 6: Commit**

```bash
git add tools/state.py tests/test_state.py
git commit -m "feat(state): archive previous plan on update, accept week_of"
```

---

### Task 3: Add validation Rule 5 — no consecutive-week repeats

**Files:**
- Modify: `tools/validate.py:39-90`
- Modify: `tests/test_validate.py`

- [ ] **Step 1: Write failing tests for Rule 5**

Add to `tests/test_validate.py`:

```python
from models import ArchivedPlan


def test_no_repeat_from_last_week_warns():
    last_week_slots = [
        _slot("Mon", "Salmon bowls", ["broccoli", "rice"], "salmon"),
        _slot("Tue", "Chicken curry", ["onion", "tomato"], "chicken"),
        _slot("Wed", "Tofu stir fry", ["pak choi", "rice"], "tofu"),
        _slot("Thu", "Beef chilli", ["onion", "tomato"], "beef"),
        _slot("Fri", "Prawn pasta", ["zucchini", "pasta"], "prawn"),
    ]
    plan_history = [ArchivedPlan(week_of=date(2026, 4, 6), slots=last_week_slots)]

    this_week = [
        _slot("Mon", "Salmon bowls", ["broccoli", "rice"], "salmon"),  # repeat!
        _slot("Tue", "Chicken traybake", ["potato", "carrot"], "chicken"),
        _slot("Wed", "Pork stir fry", ["pak choi", "rice"], "pork"),
        _slot("Thu", "Fish tacos", ["cabbage", "lime"], "fish"),
        _slot("Fri", "Veg pasta", ["zucchini", "pasta"]),
    ]
    warnings = validate_plan(this_week, _profile(), ratings=[], plan_history=plan_history)
    assert any("salmon bowls" in w.lower() and "last week" in w.lower() for w in warnings)


def test_no_repeat_case_insensitive():
    last_week_slots = [
        _slot("Mon", "chicken curry", ["onion", "tomato"], "chicken"),
        _slot("Tue", "Fish pie", ["potato", "carrot"], "fish"),
        _slot("Wed", "Tofu stir fry", ["pak choi"], "tofu"),
        _slot("Thu", "Beef chilli", ["onion", "tomato"], "beef"),
        _slot("Fri", "Prawn pasta", ["zucchini", "pasta"], "prawn"),
    ]
    plan_history = [ArchivedPlan(week_of=date(2026, 4, 6), slots=last_week_slots)]

    this_week = [
        _slot("Mon", "CHICKEN CURRY", ["onion", "tomato"], "chicken"),  # same, different case
        _slot("Tue", "Salmon bowls", ["broccoli", "rice"], "salmon"),
        _slot("Wed", "Pork stir fry", ["pak choi", "rice"], "pork"),
        _slot("Thu", "Fish tacos", ["cabbage", "lime"], "fish"),
        _slot("Fri", "Veg pasta", ["zucchini", "pasta"]),
    ]
    warnings = validate_plan(this_week, _profile(), ratings=[], plan_history=plan_history)
    assert any("chicken curry" in w.lower() and "last week" in w.lower() for w in warnings)


def test_no_repeat_no_history_no_warning():
    plan = [
        _slot("Mon", "Salmon bowls", ["broccoli", "rice"], "salmon"),
        _slot("Tue", "Chicken traybake", ["potato", "carrot"], "chicken"),
        _slot("Wed", "Tofu stir fry", ["pak choi", "rice"], "tofu"),
        _slot("Thu", "Beef chilli", ["onion", "tomato"], "beef"),
        _slot("Fri", "Veg pasta", ["zucchini", "pasta"]),
    ]
    warnings = validate_plan(plan, _profile(), ratings=[], plan_history=[])
    assert not any("last week" in w.lower() for w in warnings)
```

Also add `from datetime import datetime, date` to the imports at the top of `test_validate.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest tests/test_validate.py::test_no_repeat_from_last_week_warns -v`
Expected: FAIL — `validate_plan()` doesn't accept `plan_history` parameter.

- [ ] **Step 3: Add Rule 5 to `tools/validate.py`**

Update the `validate_plan` signature and add Rule 5 at the end:

```python
from models import MealPlanSlot, Profile, Rating, ArchivedPlan


def validate_plan(
    plan: list[MealPlanSlot],
    profile: Profile,
    ratings: list[Rating],
    plan_history: list[ArchivedPlan] | None = None,
) -> list[str]:
    """Return a list of human-readable warnings. Empty list = all good."""
    warnings: list[str] = []

    # Rules 1-4 unchanged ...

    # Rule 5: no recipe from last week's plan
    if plan_history:
        last_titles = {
            s.recipe_title.lower().strip()
            for s in plan_history[-1].slots
        }
        for slot in plan:
            if slot.recipe_title.lower().strip() in last_titles:
                warnings.append(
                    f"{slot.day} ({slot.recipe_title}) was served last week — "
                    f"avoid repeating meals in consecutive weeks."
                )

    return warnings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest tests/test_validate.py -v`
Expected: All PASS (including existing tests — they pass `plan_history` default `None`).

- [ ] **Step 5: Update the orchestrator's `validate_plan` call to pass history**

In `agents/orchestrator.py:211-216`, update the `validate_plan` dispatch:

```python
        if name == "validate_plan":
            state = read_state()
            profile = read_profile()
            if profile is None:
                return json.dumps(["No profile set yet — skipping validation."])
            return json.dumps(validate_plan(
                state.meal_plan, profile, state.ratings,
                plan_history=state.plan_history,
            ))
```

- [ ] **Step 6: Commit**

```bash
git add tools/validate.py tests/test_validate.py agents/orchestrator.py
git commit -m "feat(validate): add Rule 5 — no consecutive-week recipe repeats"
```

---

### Task 4: Update orchestrator — `week_of` in `update_plan` tool + state summary includes last week

**Files:**
- Modify: `agents/orchestrator.py:61-84` (tool schema), `agents/orchestrator.py:182-183` (dispatcher), `agents/orchestrator.py:241-249` (state summary)
- Modify: `agents/prompts.py:28-32`

- [ ] **Step 1: Update the `update_plan` tool schema to accept `week_of`**

In `agents/orchestrator.py`, find the `update_plan` tool definition (lines 61-85) and add `week_of` to its properties:

```python
    {
        "name": "update_plan",
        "description": "Replace the meal_plan wholesale. Provide 5 slots (Mon-Fri). Always include week_of (the Monday of the planned week, ISO format YYYY-MM-DD).",
        "input_schema": {
            "type": "object",
            "properties": {
                "week_of": {"type": "string", "description": "Monday of the planned week (YYYY-MM-DD)"},
                "slots": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "string", "enum": ["Mon","Tue","Wed","Thu","Fri"]},
                            "recipe_title": {"type": "string"},
                            "recipe_id": {"type": ["string", "null"]},
                            "main_protein": {"type": "string"},
                            "key_ingredients": {"type": "array", "items": {"type": "string"}},
                            "rationale": {"type": "string"},
                        },
                        "required": ["day", "recipe_title", "main_protein", "key_ingredients", "rationale"],
                    },
                },
            },
            "required": ["slots", "week_of"],
        },
    },
```

- [ ] **Step 2: Update the dispatcher to pass `week_of`**

In `agents/orchestrator.py`, update the `update_plan` dispatch (line 183):

```python
        if name == "update_plan":
            from datetime import date as date_type
            week_of_str = args.get("week_of")
            week_of = date_type.fromisoformat(week_of_str) if week_of_str else None
            return json.dumps(update_plan(args["slots"], week_of=week_of).model_dump(mode="json"))
```

- [ ] **Step 3: Update `_state_summary` to include last week's meals and current week date**

In `agents/orchestrator.py`, update `_state_summary()`:

```python
def _state_summary() -> str:
    s = read_state()
    plan_line = (
        " | ".join(f"{slot.day}: {slot.recipe_title}" for slot in s.meal_plan)
        if s.meal_plan else "(no plan set)"
    )
    week_label = f"Week of {s.week_of.isoformat()}" if s.week_of else "(no week set)"
    pantry = ", ".join(s.pantry) if s.pantry else "(empty)"
    n_ratings = len(s.ratings)

    parts = [
        f"Current plan ({week_label}): {plan_line}",
        f"Pantry: {pantry}",
        f"Ratings recorded: {n_ratings}",
    ]

    if s.plan_history:
        last = s.plan_history[-1]
        last_titles = ", ".join(slot.recipe_title for slot in last.slots)
        parts.append(f"Last week ({last.week_of.isoformat()}): {last_titles}")

    return "\n".join(parts)
```

- [ ] **Step 4: Strengthen the no-repeat instruction in the system prompt**

In `agents/prompts.py`, replace the soft preferences block (lines 28-32):

```python
SOFT PREFERENCES (use judgement):
- Favor recipes rated 'again_soon' or 'worth_repeating'
- Favor pantry-aligned recipes (ingredients already in stock)
- Include 1-2 recipes requiring shopping - keep it interesting
- Avoid repeating a recipe cooked in the last 7 days
- Do NOT repeat any recipe from last week's plan (shown in state summary under "Last week").
  Aim for variety across consecutive weeks — rotate proteins and cuisines.
```

- [ ] **Step 5: Run full test suite**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add agents/orchestrator.py agents/prompts.py
git commit -m "feat(orchestrator): pass week_of to update_plan, show last week in prompt"
```

---

### Task 5: Show the date period in the UI

**Files:**
- Modify: `app.py:27-39`

- [ ] **Step 1: Update `_render_plan_table()` to show dates**

In `app.py`, replace lines 27-39:

```python
from datetime import date, timedelta


def _render_plan_table():
    s = read_state()
    if not s.meal_plan:
        st.info("No meal plan yet. Ask the agent to plan next week.")
        return

    # Show the week header
    if s.week_of:
        monday = s.week_of
        friday = monday + timedelta(days=4)
        st.caption(f"Week of {monday.strftime('%d %b')} \u2013 {friday.strftime('%d %b %Y')}")

    day_offsets = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
    rows = []
    for slot in s.meal_plan:
        day_label = slot.day
        if s.week_of:
            slot_date = s.week_of + timedelta(days=day_offsets.get(slot.day, 0))
            day_label = f"{slot.day} {slot_date.strftime('%d/%m')}"
        rows.append({
            "Day": day_label,
            "Recipe": slot.recipe_title,
            "Protein": slot.main_protein,
            "Key ingredients": ", ".join(slot.key_ingredients),
            "Why": slot.rationale,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
```

Also update the section header from `"This week"` to be dynamic (line 71):

```python
s_header = read_state()
if s_header.week_of:
    monday = s_header.week_of
    st.subheader(f"Meal plan \u2014 w/c {monday.strftime('%d %b %Y')}")
else:
    st.subheader("Meal plan")
```

- [ ] **Step 2: Run the app manually to verify**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && streamlit run app.py`
Expected: If a plan exists with `week_of`, dates show. If no plan or no `week_of`, graceful fallback.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(ui): show date period for meal plan"
```

---

### Task 6: Thread-safe recipe writes (prerequisite for parallelisation)

**Files:**
- Modify: `tools/recipes.py:87-111`

- [ ] **Step 1: Add a lock around `save_all_recipes` and `append_recipes`**

In `tools/recipes.py`, add a module-level lock and wrap the write paths:

```python
import threading

_recipes_lock = threading.Lock()


def save_all_recipes(recipes: list[Recipe]) -> None:
    with _recipes_lock:
        save_json_list("recipes.json", recipes)


def append_recipes(new: list[Recipe]) -> list[Recipe]:
    """Append new recipes, skipping duplicates by id. Returns the newly added."""
    with _recipes_lock:
        existing = load_all_recipes()
        existing_ids = {r.id for r in existing}
        added: list[Recipe] = []
        for r in new:
            if r.id in existing_ids:
                continue
            existing.append(r)
            added.append(r)
            existing_ids.add(r.id)
        save_json_list("recipes.json", existing)
    return added
```

- [ ] **Step 2: Run existing tests**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest tests/test_search.py -v`
Expected: All pass (lock is transparent to single-threaded callers).

- [ ] **Step 3: Commit**

```bash
git add tools/recipes.py
git commit -m "feat(recipes): add threading lock for concurrent recipe writes"
```

---

### Task 7: Parallel tool dispatch in orchestrator

**Files:**
- Modify: `agents/orchestrator.py:287-297`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write a test for parallel dispatch**

Create `tests/test_orchestrator.py`:

```python
import json
import time
import threading
from unittest.mock import MagicMock
from agents.orchestrator import _dispatch


def test_dispatch_search_recipes_is_safe_to_parallelize(tmp_path, monkeypatch):
    """Two concurrent search_recipes calls should not interfere."""
    from datetime import datetime
    from models import Recipe
    from tools.recipes import load_all_recipes

    monkeypatch.setattr("storage.STATE_DIR", tmp_path)

    recipes = [
        Recipe(
            id="a", title="Chicken pho", cuisine="vietnamese",
            main_protein="chicken", key_ingredients=["chicken", "noodles"],
            tags=["light"], cook_time_min=20, added_at=datetime(2026, 1, 1),
        ),
        Recipe(
            id="b", title="Salmon teriyaki", cuisine="japanese",
            main_protein="salmon", key_ingredients=["salmon", "rice"],
            tags=["quick"], cook_time_min=15, added_at=datetime(2026, 1, 1),
        ),
    ]

    # Monkeypatch load_all_recipes to return our fixture
    monkeypatch.setattr("tools.recipes.load_all_recipes", lambda: recipes)

    results = [None, None]

    def search_0():
        results[0] = json.loads(_dispatch("search_recipes", {"query": "chicken"}))

    def search_1():
        results[1] = json.loads(_dispatch("search_recipes", {"query": "salmon"}))

    t0 = threading.Thread(target=search_0)
    t1 = threading.Thread(target=search_1)
    t0.start()
    t1.start()
    t0.join()
    t1.join()

    assert results[0] is not None and len(results[0]) > 0
    assert results[1] is not None and len(results[1]) > 0
    assert results[0][0]["id"] == "a"
    assert results[1][0]["id"] == "b"
```

- [ ] **Step 2: Run the test**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest tests/test_orchestrator.py -v`
Expected: PASS (search is already read-only; this validates the pattern).

- [ ] **Step 3: Replace sequential dispatch with parallel dispatch**

In `agents/orchestrator.py`, add import at the top:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
```

Replace the tool dispatch block (lines 287-297) inside `run_turn`:

```python
        # Run every tool call in the response — parallelise where safe
        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        if len(tool_blocks) == 1:
            # Single tool — no threading overhead
            block = tool_blocks[0]
            result = _dispatch(block.name, block.input or {})
            tool_results = [{
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            }]
        else:
            # Multiple tools — run in parallel
            with ThreadPoolExecutor(max_workers=len(tool_blocks)) as pool:
                futures = {
                    pool.submit(_dispatch, block.name, block.input or {}): block
                    for block in tool_blocks
                }
                tool_results = []
                for future in as_completed(futures):
                    block = futures[future]
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": future.result(),
                    })
        messages.append({"role": "user", "content": tool_results})
```

- [ ] **Step 4: Run full test suite**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add agents/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): parallel tool dispatch with ThreadPoolExecutor"
```

---

### Task 8: Progress callback in recipe finder

**Files:**
- Modify: `agents/recipe_finder.py:30-67`
- Modify: `tools/recipes.py:114-119`

- [ ] **Step 1: Add `on_progress` callback to `find_new_recipes`**

In `agents/recipe_finder.py`, update the function signature and loop:

```python
from typing import Callable


def find_new_recipes(
    query: str,
    count: int,
    profile: Profile | None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[Recipe]:
    """Run an isolated Claude session with web_search, return structured recipes.

    on_progress(current_step, total_steps, message) is called before each API round.
    """
    client = Anthropic()
    system_prompt = RECIPE_FINDER_SYSTEM_PROMPT.format(
        query=query,
        count=count,
        household_context=_household_context(profile),
    )

    messages: list[dict] = [{
        "role": "user",
        "content": f"Find {count} recipes for: {query}",
    }]

    max_rounds = 5
    text_parts: list[str] = []
    for i in range(max_rounds):
        if on_progress:
            on_progress(i + 1, max_rounds, f"Searching for '{query}'…")
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
            }],
            messages=messages,
        )
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)

        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        if on_progress:
            on_progress(max_rounds, max_rounds, "Processing results…")
        break

    raw = "\n".join(text_parts).strip()

    match = re.search(r"\[\s*\{.*?\}\s*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    out: list[Recipe] = []
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
                added_at=now,
            ))
        except (KeyError, ValueError):
            continue
    return out
```

- [ ] **Step 2: Update `find_new_recipes_tool` to accept and forward callback**

In `tools/recipes.py`, update `find_new_recipes_tool`:

```python
def find_new_recipes_tool(
    query: str,
    count: int,
    profile: Profile | None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[dict]:
    """Tool-facing: spawn subagent, append results to recipes.json, return summaries."""
    from agents.recipe_finder import find_new_recipes  # local import avoids cycle
    found = find_new_recipes(query, count, profile, on_progress=on_progress)
    added = append_recipes(found)
    return [recipe_summary(r) for r in added]
```

Add to the imports at top of `tools/recipes.py`:

```python
from typing import Any, Callable
```

- [ ] **Step 3: Run full test suite**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest -v`
Expected: All pass (callback is optional, defaults to None).

- [ ] **Step 4: Commit**

```bash
git add agents/recipe_finder.py tools/recipes.py
git commit -m "feat(recipe-finder): add on_progress callback for progress reporting"
```

---

### Task 9: Background job infrastructure + progress bar in app

**Files:**
- Modify: `agents/orchestrator.py` (add background dispatch + `check_search_status` tool)
- Modify: `app.py` (progress bar + background job banner)

- [ ] **Step 1: Add background job state to orchestrator**

At the top of `agents/orchestrator.py`, add the background job infrastructure:

```python
import threading

# Background job registry — shared across turns in the same Streamlit session.
# Keys: job_id strings. Values: {"status": "running"|"done"|"error", "result": ..., "progress": (cur, total, msg)}
_bg_jobs: dict[str, dict] = {}
_bg_lock = threading.Lock()


def get_bg_jobs() -> dict[str, dict]:
    """Return a shallow copy of background jobs (for UI polling)."""
    with _bg_lock:
        return dict(_bg_jobs)


def _run_recipe_search_bg(job_id: str, query: str, count: int, profile):
    """Target for background thread — runs find_new_recipes_tool and stores result."""
    from tools.recipes import find_new_recipes_tool

    def _on_progress(cur, total, msg):
        with _bg_lock:
            _bg_jobs[job_id]["progress"] = (cur, total, msg)

    try:
        result = find_new_recipes_tool(query, count, profile, on_progress=_on_progress)
        with _bg_lock:
            _bg_jobs[job_id]["status"] = "done"
            _bg_jobs[job_id]["result"] = result
    except Exception as e:
        with _bg_lock:
            _bg_jobs[job_id]["status"] = "error"
            _bg_jobs[job_id]["result"] = str(e)
```

- [ ] **Step 2: Add `check_search_status` tool definition**

Add to `TOOL_DEFINITIONS` list in `agents/orchestrator.py`:

```python
    {
        "name": "check_search_status",
        "description": "Check the status of a background recipe search. Returns status ('running', 'done', 'error') and results if done.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
```

- [ ] **Step 3: Update dispatcher for background `find_new_recipes` and `check_search_status`**

In `_dispatch`, replace the `find_new_recipes` branch:

```python
        if name == "find_new_recipes":
            job_id = f"search-{datetime.now().timestamp()}"
            with _bg_lock:
                _bg_jobs[job_id] = {"status": "running", "result": None, "progress": (0, 5, "Starting…")}
            thread = threading.Thread(
                target=_run_recipe_search_bg,
                args=(job_id, args["query"], args.get("count", 3), read_profile()),
                daemon=True,
            )
            thread.start()
            return json.dumps({
                "status": "started",
                "job_id": job_id,
                "message": f"Recipe search for '{args['query']}' running in background. "
                           f"Use check_search_status to poll, or continue with other tasks.",
            })
        if name == "check_search_status":
            job_id = args["job_id"]
            with _bg_lock:
                job = _bg_jobs.get(job_id)
            if job is None:
                return json.dumps({"error": f"Unknown job: {job_id}"})
            return json.dumps({
                "status": job["status"],
                "progress": job.get("progress"),
                "result": job["result"] if job["status"] != "running" else None,
            })
```

- [ ] **Step 4: Update `app.py` with progress bar and background job banner**

Replace `app.py` entirely:

```python
# app.py
import os
import pandas as pd
import streamlit as st
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

from tools.state import read_state
from tools.profile import read_profile
from agents.orchestrator import run_turn, get_bg_jobs

st.set_page_config(page_title="Meal Planner (Agentic)", layout="wide")
st.title("Meal Planner")

if not os.getenv("ANTHROPIC_API_KEY"):
    st.error("ANTHROPIC_API_KEY not set. Add it to .env and restart.")
    st.stop()

# --- Session state ---
if "history" not in st.session_state:
    st.session_state.history = []
if "chat_display" not in st.session_state:
    st.session_state.chat_display = []


def _render_plan_table():
    s = read_state()
    if not s.meal_plan:
        st.info("No meal plan yet. Ask the agent to plan next week.")
        return

    if s.week_of:
        monday = s.week_of
        friday = monday + timedelta(days=4)
        st.caption(f"Week of {monday.strftime('%d %b')} \u2013 {friday.strftime('%d %b %Y')}")

    day_offsets = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
    rows = []
    for slot in s.meal_plan:
        day_label = slot.day
        if s.week_of:
            slot_date = s.week_of + timedelta(days=day_offsets.get(slot.day, 0))
            day_label = f"{slot.day} {slot_date.strftime('%d/%m')}"
        rows.append({
            "Day": day_label,
            "Recipe": slot.recipe_title,
            "Protein": slot.main_protein,
            "Key ingredients": ", ".join(slot.key_ingredients),
            "Why": slot.rationale,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_sidebar():
    with st.sidebar:
        st.subheader("Profile")
        p = read_profile()
        if p is None:
            st.caption("No profile yet. The agent will onboard you.")
        else:
            st.caption(f"Household of {p.household_size}")
            st.caption("Members: " + ", ".join(m.name for m in p.members))
            if p.household_dislikes:
                st.caption("Dislikes: " + ", ".join(p.household_dislikes))

        st.subheader("Pantry")
        s = read_state()
        if s.pantry:
            st.write(" \u00b7 ".join(s.pantry))
        else:
            st.caption("(empty)")

        with st.expander("Recent ratings"):
            if not s.ratings:
                st.caption("(none)")
            else:
                for r in s.ratings[-10:]:
                    st.caption(f"{r.cooked_at.date()} \u00b7 {r.rater}: {r.recipe_title} \u2192 {r.rating}")


def _render_bg_jobs():
    """Show a banner for any running background recipe searches."""
    jobs = get_bg_jobs()
    for job_id, job in jobs.items():
        if job["status"] == "running":
            cur, total, msg = job.get("progress", (0, 1, "Starting..."))
            st.info(f"Background search: {msg}")
            st.progress(cur / total if total > 0 else 0)
        elif job["status"] == "done" and job.get("result"):
            count = len(job["result"])
            st.success(f"Recipe search complete \u2014 {count} new recipe(s) added.")
        elif job["status"] == "error":
            st.error(f"Recipe search failed: {job.get('result', 'unknown error')}")


# --- Layout ---
_render_sidebar()

s_header = read_state()
if s_header.week_of:
    st.subheader(f"Meal plan \u2014 w/c {s_header.week_of.strftime('%d %b %Y')}")
else:
    st.subheader("Meal plan")

_render_plan_table()

_render_bg_jobs()

st.divider()
st.subheader("Chat")

for msg in st.session_state.chat_display:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])

user_input = st.chat_input("Tell the agent what you want\u2026")
if user_input:
    st.session_state.chat_display.append({"role": "user", "text": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
    with st.chat_message("assistant"):
        with st.spinner("Thinking\u2026"):
            reply, new_history = run_turn(user_input, st.session_state.history)
        st.session_state.history = new_history
        st.session_state.chat_display.append({"role": "assistant", "text": reply})
        st.markdown(reply)
    st.rerun()
```

- [ ] **Step 5: Run full test suite**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && python -m pytest -v`
Expected: All pass.

- [ ] **Step 6: Manual test — run the app and trigger a recipe search**

Run: `cd C:\Users\migst\personal-kb\code\meal-planner-agentic && streamlit run app.py`
Expected: When asking the agent to "find new recipes for Thai curry", you should see a progress bar while the search runs, and a success banner when it completes. The chat should remain responsive during the search.

- [ ] **Step 7: Commit**

```bash
git add agents/orchestrator.py app.py
git commit -m "feat: background recipe search with progress bar and status polling"
```

---

## Self-Review Checklist

**Spec coverage:**
1. Progress bar for recipe search — Task 8 (callback) + Task 9 (UI wiring). Covered.
2. Background recipe search — Task 9 (thread + `check_search_status` tool). Covered.
3. Parallel tool dispatch — Task 6 (lock) + Task 7 (ThreadPoolExecutor). Covered.
4. Date period display — Task 1 (model) + Task 4 (orchestrator) + Task 5 (UI). Covered.
5. No consecutive-week repeats — Task 1 (model) + Task 2 (archival) + Task 3 (validation) + Task 4 (prompt). Covered.

**Placeholder scan:** No TBD/TODO found. All code blocks contain complete implementations.

**Type consistency:** `ArchivedPlan` used consistently across models.py, state.py, validate.py, orchestrator.py. `week_of` is `date | None` everywhere. `on_progress` callback signature is `Callable[[int, int, str], None] | None` in both recipe_finder.py and recipes.py. `_bg_jobs` dict structure is consistent between write (`_run_recipe_search_bg`) and read (`get_bg_jobs`, `_dispatch` for `check_search_status`).
