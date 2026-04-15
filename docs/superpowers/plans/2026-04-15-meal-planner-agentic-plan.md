# Meal Planner (Agentic) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a chat-driven weekly meal planner. User talks to an agent; the agent reads/writes a JSON-backed meal plan, pantry, and recipe library; all edits happen through natural language.

**Architecture:** Streamlit single-page app wrapping a Claude agent loop. Orchestrator agent (Sonnet 4.6) has tools for state CRUD, recipe search, and a `find_new_recipes` tool that spawns an isolated RecipeFinder subagent with web search. Three JSON files in `state/` are the source of truth: `profile.json` (household), `recipes.json` (saved recipes), `state.json` (plan + pantry + ratings).

**Tech Stack:** Python 3.11+, `anthropic` SDK (Python), Streamlit, Pydantic v2, pytest. No database, no ORM, no Docker.

**Spec:** `docs/superpowers/specs/2026-04-15-meal-planner-agentic-design.md`

---

## File layout (target end-state)

```
meal-planner-agentic/
  app.py                     # Streamlit entrypoint
  agents/
    __init__.py
    orchestrator.py          # builds the agent loop + tool dispatch
    recipe_finder.py         # subagent factory
    prompts.py               # system prompt constants
  tools/
    __init__.py
    profile.py               # read_profile, update_profile
    state.py                 # read_state, update_plan, update_pantry, record_rating
    recipes.py               # list/get/search/find_new recipes
    validate.py              # validate_plan (pure)
  models.py                  # Pydantic models
  storage.py                 # atomic JSON read/write
  state/                     # gitignored, created at runtime
  tests/
    __init__.py
    test_models.py
    test_storage.py
    test_validate.py
    test_search.py
  pyproject.toml
  README.md
  .env.example
  .gitignore
```

**SDK choice:** this plan uses the `anthropic` Python SDK directly (stable tool-use loop). The `claude-agent-sdk` package can be swapped in later if desired — the tool definitions transfer cleanly.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `README.md`
- Create: `agents/__init__.py`, `tools/__init__.py`, `tests/__init__.py` (empty)

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "meal-planner-agentic"
version = "0.1.0"
description = "Chat-driven weekly meal planner with Claude agents"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "streamlit>=1.40.0",
    "pydantic>=2.8.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["agents", "tools"]
py-modules = ["app", "models", "storage"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.env.example`**

```
ANTHROPIC_API_KEY=
```

- [ ] **Step 3: Create `.gitignore`**

```
state/
.env
__pycache__/
*.pyc
.pytest_cache/
.venv/
*.egg-info/
dist/
build/
```

- [ ] **Step 4: Create placeholder `README.md`**

```markdown
# Meal Planner (Agentic)

Chat-driven weekly meal planner. See `docs/superpowers/specs/2026-04-15-meal-planner-agentic-design.md`.

## Setup
```
pip install -e ".[dev]"
cp .env.example .env  # fill ANTHROPIC_API_KEY
streamlit run app.py
```
```

- [ ] **Step 5: Create empty `__init__.py` files**

Empty files at `agents/__init__.py`, `tools/__init__.py`, `tests/__init__.py`.

- [ ] **Step 6: Verify install works**

Run: `pip install -e ".[dev]"`
Expected: clean install, `pytest --version` works.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .env.example .gitignore README.md agents/__init__.py tools/__init__.py tests/__init__.py
git commit -m "chore: scaffold meal-planner-agentic project"
```

---

### Task 2: Pydantic models

**Files:**
- Create: `models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from datetime import datetime
from models import Profile, Member, Recipe, Rating, MealPlanSlot, State


def test_profile_roundtrip():
    p = Profile(
        household_size=4,
        members=[
            Member(name="Ana", is_adult=True, dislikes=["mushrooms"]),
            Member(name="Mia", is_adult=False, dislikes=["olives"]),
        ],
        household_dislikes=["liver"],
        dietary_rules=["≥1 fish/week"],
        preferred_cuisines=["italian", "sg-chinese"],
        notes="",
    )
    s = p.model_dump_json()
    p2 = Profile.model_validate_json(s)
    assert p2 == p


def test_recipe_defaults():
    r = Recipe(
        id="salmon-teriyaki",
        title="Salmon teriyaki",
        cuisine="japanese",
        main_protein="salmon",
        key_ingredients=["salmon", "soy sauce", "mirin"],
        tags=["quick", "kid-friendly"],
        cook_time_min=25,
        added_at=datetime(2026, 4, 15),
    )
    assert r.times_cooked == 0
    assert r.last_cooked is None
    assert r.avg_rating is None
    assert r.source_url is None


def test_meal_plan_slot_optional_recipe_id():
    slot = MealPlanSlot(
        day="Mon",
        recipe_title="Pantry pasta",
        recipe_id=None,
        key_ingredients=["pasta", "tomato", "basil"],
        rationale="Uses what's in the pantry",
    )
    assert slot.recipe_id is None


def test_state_empty_defaults():
    s = State(meal_plan=[], pantry=[], ratings=[], last_updated=datetime(2026, 4, 15))
    assert s.meal_plan == []
    assert s.pantry == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: ImportError — `models` module doesn't exist.

- [ ] **Step 3: Implement `models.py`**

```python
# models.py
from datetime import datetime
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
    key_ingredients: list[str]
    rationale: str


class State(BaseModel):
    meal_plan: list[MealPlanSlot] = Field(default_factory=list)
    pantry: list[str] = Field(default_factory=list)
    ratings: list[Rating] = Field(default_factory=list)
    last_updated: datetime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: add Pydantic models for profile, recipe, state"
```

---

### Task 3: Atomic JSON storage

**Files:**
- Create: `storage.py`
- Test: `tests/test_storage.py`

Storage must be atomic — write to a temp file, then `os.replace` — so a crash mid-write doesn't corrupt state.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_storage.py
from datetime import datetime
from pathlib import Path
import json
import pytest
from models import Profile, Member, State
from storage import load_json, save_json, STATE_DIR


@pytest.fixture
def tmp_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("storage.STATE_DIR", tmp_path)
    return tmp_path


def test_load_missing_returns_none(tmp_state_dir):
    assert load_json("profile.json", Profile) is None


def test_save_then_load_roundtrip(tmp_state_dir):
    p = Profile(
        household_size=2,
        members=[Member(name="A", is_adult=True, dislikes=[])],
        household_dislikes=[],
        dietary_rules=[],
        preferred_cuisines=[],
        notes="",
    )
    save_json("profile.json", p)
    loaded = load_json("profile.json", Profile)
    assert loaded == p


def test_save_is_atomic(tmp_state_dir):
    # After a save, there should be no stray .tmp files
    s = State(meal_plan=[], pantry=[], ratings=[], last_updated=datetime(2026, 4, 15))
    save_json("state.json", s)
    assert (tmp_state_dir / "state.json").exists()
    assert not any(p.name.endswith(".tmp") for p in tmp_state_dir.iterdir())


def test_save_overwrites_cleanly(tmp_state_dir):
    s1 = State(meal_plan=[], pantry=["eggs"], ratings=[], last_updated=datetime(2026, 4, 15))
    s2 = State(meal_plan=[], pantry=["milk"], ratings=[], last_updated=datetime(2026, 4, 16))
    save_json("state.json", s1)
    save_json("state.json", s2)
    loaded = load_json("state.json", State)
    assert loaded.pantry == ["milk"]


def test_load_returns_typed_model(tmp_state_dir):
    # Manually write a file; load should parse into the model
    (tmp_state_dir / "profile.json").write_text(
        json.dumps({
            "household_size": 1,
            "members": [{"name": "X", "is_adult": True, "dislikes": []}],
            "household_dislikes": [],
            "dietary_rules": [],
            "preferred_cuisines": [],
            "notes": "",
        })
    )
    loaded = load_json("profile.json", Profile)
    assert isinstance(loaded, Profile)
    assert loaded.household_size == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v`
Expected: ImportError — `storage` module doesn't exist.

- [ ] **Step 3: Implement `storage.py`**

```python
# storage.py
import os
from pathlib import Path
from typing import TypeVar, Type
from pydantic import BaseModel

STATE_DIR = Path(__file__).parent / "state"

T = TypeVar("T", bound=BaseModel)


def _ensure_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_json(filename: str, model: Type[T]) -> T | None:
    """Load and parse a JSON file into the given Pydantic model. Returns None if missing."""
    path = STATE_DIR / filename
    if not path.exists():
        return None
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def load_json_list(filename: str, model: Type[T]) -> list[T]:
    """Load a JSON file containing a list of models. Returns [] if missing."""
    path = STATE_DIR / filename
    if not path.exists():
        return []
    import json
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [model.model_validate(item) for item in raw]


def save_json(filename: str, value: BaseModel) -> None:
    """Atomically write a Pydantic model to STATE_DIR/filename."""
    _ensure_dir()
    path = STATE_DIR / filename
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save_json_list(filename: str, values: list[BaseModel]) -> None:
    """Atomically write a list of Pydantic models."""
    _ensure_dir()
    path = STATE_DIR / filename
    tmp = path.with_suffix(path.suffix + ".tmp")
    import json
    tmp.write_text(
        json.dumps([v.model_dump(mode="json") for v in values], indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage.py
git commit -m "feat: atomic JSON storage helpers"
```

---

### Task 4: Plan validator (pure function)

**Files:**
- Create: `tools/validate.py`
- Test: `tests/test_validate.py`

Hard rules from spec §8: ≥1 fish, every meal has veg, no mutual `never_again`, no household dislikes. Returns list of warnings (non-blocking).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validate.py
from datetime import datetime
from models import Profile, Member, MealPlanSlot, Rating
from tools.validate import validate_plan, PRODUCE_KEYWORDS


def _profile(**overrides):
    base = dict(
        household_size=2,
        members=[
            Member(name="A", is_adult=True, dislikes=[]),
            Member(name="B", is_adult=True, dislikes=[]),
        ],
        household_dislikes=[],
        dietary_rules=[],
        preferred_cuisines=[],
        notes="",
    )
    base.update(overrides)
    return Profile(**base)


def _slot(day, title, ingredients, protein_hint=None):
    # protein_hint kept in key_ingredients so validator can detect fish
    ings = list(ingredients)
    if protein_hint and protein_hint not in ings:
        ings.insert(0, protein_hint)
    return MealPlanSlot(
        day=day, recipe_title=title, recipe_id=None,
        key_ingredients=ings, rationale="test",
    )


def test_valid_plan_no_warnings():
    plan = [
        _slot("Mon", "Salmon bowls", ["broccoli", "rice"], "salmon"),
        _slot("Tue", "Chicken traybake", ["potato", "carrot"], "chicken"),
        _slot("Wed", "Tofu stir fry", ["pak choi", "rice"], "tofu"),
        _slot("Thu", "Beef chilli", ["onion", "tomato"], "beef"),
        _slot("Fri", "Veg pasta", ["zucchini", "pasta"], "mushrooms-free"),
    ]
    assert validate_plan(plan, _profile(), ratings=[]) == []


def test_no_fish_warning():
    plan = [
        _slot("Mon", "Chicken bowls", ["broccoli", "rice"], "chicken"),
        _slot("Tue", "Beef stew", ["potato", "carrot"], "beef"),
        _slot("Wed", "Tofu stir fry", ["pak choi", "rice"], "tofu"),
        _slot("Thu", "Pork chops", ["apple", "cabbage"], "pork"),
        _slot("Fri", "Veg pasta", ["zucchini", "pasta"]),
    ]
    warnings = validate_plan(plan, _profile(), ratings=[])
    assert any("fish" in w.lower() for w in warnings)


def test_missing_veg_warning():
    plan = [
        _slot("Mon", "Plain rice", ["rice"]),  # no produce
    ]
    warnings = validate_plan(plan, _profile(), ratings=[])
    assert any("vegetable" in w.lower() and "Mon" in w for w in warnings)


def test_household_dislike_warning():
    profile = _profile(household_dislikes=["mushrooms"])
    plan = [
        _slot("Mon", "Mushroom risotto", ["mushrooms", "rice"]),
    ]
    warnings = validate_plan(plan, profile, ratings=[])
    assert any("mushrooms" in w.lower() and "Mon" in w for w in warnings)


def test_both_adults_never_again_warning():
    profile = _profile()
    ratings = [
        Rating(recipe_title="Liver pie", rater="A", rating="never_again",
               cooked_at=datetime(2026, 3, 1)),
        Rating(recipe_title="Liver pie", rater="B", rating="never_again",
               cooked_at=datetime(2026, 3, 1)),
    ]
    plan = [_slot("Mon", "Liver pie", ["liver", "onion"])]
    warnings = validate_plan(plan, profile, ratings=ratings)
    assert any("never_again" in w.lower() or "never again" in w.lower() for w in warnings)


def test_single_adult_never_again_does_not_warn():
    profile = _profile()
    ratings = [
        Rating(recipe_title="Liver pie", rater="A", rating="never_again",
               cooked_at=datetime(2026, 3, 1)),
    ]
    plan = [_slot("Mon", "Liver pie", ["liver", "onion"])]
    warnings = validate_plan(plan, profile, ratings=ratings)
    # Fish and veg warnings might fire, but no "never again" warning
    assert not any("never_again" in w.lower() or "never again" in w.lower() for w in warnings)


def test_produce_keywords_basic():
    # Sanity: basic veg are recognised
    assert "broccoli" in PRODUCE_KEYWORDS
    assert "carrot" in PRODUCE_KEYWORDS
    assert "tomato" in PRODUCE_KEYWORDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validate.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `tools/validate.py`**

```python
# tools/validate.py
from models import MealPlanSlot, Profile, Rating

FISH_KEYWORDS = {
    "salmon", "tuna", "cod", "haddock", "trout", "mackerel", "sardine",
    "anchovy", "seabass", "sea bass", "tilapia", "pollock", "fish",
    "prawn", "shrimp", "squid", "calamari", "octopus", "mussel", "clam",
    "oyster", "scallop", "crab", "lobster",
}

PRODUCE_KEYWORDS = {
    # leafy + cruciferous
    "spinach", "kale", "lettuce", "cabbage", "pak choi", "bok choy",
    "broccoli", "cauliflower", "brussels sprout", "chard", "rocket", "arugula",
    # roots
    "carrot", "potato", "sweet potato", "beetroot", "beet", "parsnip", "turnip",
    "radish", "onion", "leek", "shallot", "garlic", "ginger",
    # fruiting
    "tomato", "cucumber", "zucchini", "courgette", "pepper", "capsicum",
    "eggplant", "aubergine", "pumpkin", "squash", "avocado",
    # pods / beans
    "green bean", "snap pea", "snow pea", "pea", "edamame", "asparagus",
    "okra", "corn", "sweetcorn",
    # alliums / herbs that count
    "spring onion", "scallion", "mushroom",
    # fruit that counts in savoury dishes
    "apple", "pear", "lemon", "lime", "orange",
}


def _matches_any(ingredients: list[str], keywords: set[str]) -> bool:
    lowered = [i.lower() for i in ingredients]
    for ing in lowered:
        for kw in keywords:
            if kw in ing:
                return True
    return False


def validate_plan(
    plan: list[MealPlanSlot],
    profile: Profile,
    ratings: list[Rating],
) -> list[str]:
    """Return a list of human-readable warnings. Empty list = all good."""
    warnings: list[str] = []

    # Rule 1: ≥1 fish meal per week
    if plan and not any(_matches_any(s.key_ingredients, FISH_KEYWORDS) for s in plan):
        warnings.append("No fish this week — at least 1 fish meal is expected.")

    # Rule 2: every meal has a vegetable
    for slot in plan:
        if not _matches_any(slot.key_ingredients, PRODUCE_KEYWORDS):
            warnings.append(
                f"{slot.day} ({slot.recipe_title}) has no vegetable listed."
            )

    # Rule 3: no household dislike
    dislikes = {d.lower() for d in profile.household_dislikes}
    for slot in plan:
        for ing in slot.key_ingredients:
            for d in dislikes:
                if d in ing.lower():
                    warnings.append(
                        f"{slot.day} ({slot.recipe_title}) violates household dislike: {d}"
                    )
                    break

    # Rule 4: no recipe both adults rated never_again
    adult_names = {m.name for m in profile.members if m.is_adult}
    never_again_by_recipe: dict[str, set[str]] = {}
    for r in ratings:
        if r.rating == "never_again" and r.rater in adult_names:
            never_again_by_recipe.setdefault(r.recipe_title, set()).add(r.rater)
    mutual_never = {
        title for title, raters in never_again_by_recipe.items()
        if raters >= adult_names and len(adult_names) > 0
    }
    for slot in plan:
        if slot.recipe_title in mutual_never:
            warnings.append(
                f"{slot.day} ({slot.recipe_title}) was rated never_again by both adults."
            )

    return warnings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validate.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/validate.py tests/test_validate.py
git commit -m "feat: pure plan validator with hard-rule warnings"
```

---

### Task 5: Recipe search (pure logic)

**Files:**
- Create: `tools/recipes.py` (partial — search-only for now)
- Test: `tests/test_search.py`

Implements `list_recipes` and `search_recipes`. `find_new_recipes` is added later in Task 10.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_search.py
from datetime import datetime
from models import Recipe
from tools.recipes import search_recipes, list_recipes, recipe_summary


def _r(id, title, cuisine="x", protein="chicken", tags=None, key=None,
       avg_rating=None, times=0, cook=20):
    return Recipe(
        id=id, title=title, cuisine=cuisine, main_protein=protein,
        key_ingredients=key or ["onion"], tags=tags or [], cook_time_min=cook,
        avg_rating=avg_rating, times_cooked=times,
        added_at=datetime(2026, 1, 1),
    )


RECIPES = [
    _r("a", "Chicken pho", cuisine="vietnamese", protein="chicken",
       tags=["light", "quick"], key=["chicken", "rice noodles", "bean sprouts"],
       avg_rating=4.5, times=3),
    _r("b", "Chicken curry", cuisine="indian", protein="chicken",
       tags=["comfort"], key=["chicken", "coconut milk", "onion"],
       avg_rating=3.5, times=5),
    _r("c", "Salmon teriyaki", cuisine="japanese", protein="salmon",
       tags=["quick", "kid-friendly"], key=["salmon", "broccoli", "rice"],
       avg_rating=4.8, times=2),
    _r("d", "Beef stew", cuisine="british", protein="beef",
       tags=["comfort"], key=["beef", "potato", "carrot"],
       avg_rating=None, times=0),
]


def test_recipe_summary_is_compact():
    s = recipe_summary(RECIPES[0])
    assert "id" in s and "title" in s and "cuisine" in s
    assert "key_ingredients" not in s  # full details excluded
    assert "source_url" not in s


def test_list_recipes_returns_summaries():
    out = list_recipes(RECIPES)
    assert len(out) == 4
    assert all("id" in r for r in out)


def test_list_recipes_filters_by_cuisine():
    out = list_recipes(RECIPES, filters={"cuisine": "japanese"})
    assert len(out) == 1
    assert out[0]["id"] == "c"


def test_list_recipes_filters_by_protein():
    out = list_recipes(RECIPES, filters={"main_protein": "chicken"})
    assert {r["id"] for r in out} == {"a", "b"}


def test_search_matches_title():
    out = search_recipes(RECIPES, query="pho")
    assert out and out[0]["id"] == "a"


def test_search_matches_ingredients():
    out = search_recipes(RECIPES, query="bean sprouts")
    assert out and out[0]["id"] == "a"


def test_search_matches_tags():
    out = search_recipes(RECIPES, query="kid-friendly")
    assert out and out[0]["id"] == "c"


def test_search_ranks_by_rating_then_times_cooked():
    # Both match "chicken" — higher avg_rating wins
    out = search_recipes(RECIPES, query="chicken")
    assert [r["id"] for r in out[:2]] == ["a", "b"]


def test_search_unrated_last():
    # Beef stew has no rating, 0 times cooked — ranks last among matches
    out = search_recipes(RECIPES, query="comfort")
    # b (rated) before d (unrated)
    ids = [r["id"] for r in out]
    assert ids.index("b") < ids.index("d")


def test_search_respects_top_k():
    out = search_recipes(RECIPES, query="chicken", top_k=1)
    assert len(out) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_search.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `tools/recipes.py` (search + list only)**

```python
# tools/recipes.py
from typing import Any
from models import Recipe


SUMMARY_FIELDS = ("id", "title", "cuisine", "main_protein", "avg_rating",
                  "times_cooked", "tags", "cook_time_min")


def recipe_summary(r: Recipe) -> dict[str, Any]:
    """Compact representation — cheap to list even with hundreds of recipes."""
    return {
        "id": r.id,
        "title": r.title,
        "cuisine": r.cuisine,
        "main_protein": r.main_protein,
        "avg_rating": r.avg_rating,
        "times_cooked": r.times_cooked,
        "tags": r.tags,
        "cook_time_min": r.cook_time_min,
    }


def list_recipes(
    recipes: list[Recipe],
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return compact summaries, optionally filtered by exact-match fields."""
    filters = filters or {}
    out = []
    for r in recipes:
        if all(getattr(r, k, None) == v for k, v in filters.items()):
            out.append(recipe_summary(r))
    return out


def _score_match(r: Recipe, query: str) -> int:
    """Count how many query tokens appear in searchable fields."""
    q_tokens = [t for t in query.lower().split() if t]
    if not q_tokens:
        return 0
    haystack = " ".join([
        r.title.lower(),
        r.cuisine.lower(),
        r.main_protein.lower(),
        " ".join(t.lower() for t in r.tags),
        " ".join(i.lower() for i in r.key_ingredients),
    ])
    return sum(1 for t in q_tokens if t in haystack)


def search_recipes(
    recipes: list[Recipe],
    query: str,
    filters: dict[str, Any] | None = None,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """Match query against title/tags/ingredients/cuisine. Rank by (match count,
    avg_rating desc, times_cooked desc). Apply exact-match filters first."""
    filters = filters or {}
    candidates = [
        r for r in recipes
        if all(getattr(r, k, None) == v for k, v in filters.items())
    ]
    scored: list[tuple[int, float, int, Recipe]] = []
    for r in candidates:
        s = _score_match(r, query)
        if s == 0 and query.strip():
            continue
        scored.append((
            s,
            r.avg_rating if r.avg_rating is not None else -1.0,
            r.times_cooked,
            r,
        ))
    # Higher score first, then higher rating, then more times cooked
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    return [recipe_summary(r) for _, _, _, r in scored[:top_k]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_search.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/recipes.py tests/test_search.py
git commit -m "feat: recipe search + list with ranking"
```

---

### Task 6: Profile tools

**Files:**
- Create: `tools/profile.py`

No new tests — this is a thin wrapper over `storage.py`. Smoke-covered in Task 12 integration run.

- [ ] **Step 1: Implement `tools/profile.py`**

```python
# tools/profile.py
from models import Profile
from storage import load_json, save_json


def read_profile() -> Profile | None:
    return load_json("profile.json", Profile)


def update_profile(partial: dict) -> Profile:
    """Merge partial updates into profile.json. Create if missing.

    The agent may pass any subset of Profile fields. Fields not present
    are preserved from the existing profile.
    """
    current = read_profile()
    merged: dict
    if current is None:
        # First time — require all mandatory fields
        merged = partial
    else:
        merged = current.model_dump()
        merged.update(partial)
    new_profile = Profile.model_validate(merged)
    save_json("profile.json", new_profile)
    return new_profile
```

- [ ] **Step 2: Sanity check**

Run: `python -c "from tools.profile import read_profile, update_profile; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add tools/profile.py
git commit -m "feat: profile read/update tools"
```

---

### Task 7: State tools

**Files:**
- Create: `tools/state.py`

- [ ] **Step 1: Implement `tools/state.py`**

```python
# tools/state.py
from datetime import datetime
from models import State, MealPlanSlot, Rating
from storage import load_json, save_json


def _now() -> datetime:
    return datetime.now()


def read_state() -> State:
    s = load_json("state.json", State)
    if s is None:
        s = State(meal_plan=[], pantry=[], ratings=[], last_updated=_now())
        save_json("state.json", s)
    return s


def update_plan(slots: list[dict]) -> State:
    """Replace meal_plan wholesale with the given slots."""
    s = read_state()
    s.meal_plan = [MealPlanSlot.model_validate(slot) for slot in slots]
    s.last_updated = _now()
    save_json("state.json", s)
    return s


def update_pantry(add: list[str] | None = None, remove: list[str] | None = None) -> State:
    """Apply a diff to the pantry. Items are normalised to lowercase, stripped."""
    s = read_state()
    current = {p.lower().strip() for p in s.pantry}
    for item in (add or []):
        current.add(item.lower().strip())
    for item in (remove or []):
        current.discard(item.lower().strip())
    s.pantry = sorted(current)
    s.last_updated = _now()
    save_json("state.json", s)
    return s


def record_rating(recipe_title: str, rater: str, rating: str,
                  cooked_at: str | None = None) -> State:
    """Append a rating. cooked_at is an ISO-8601 string or defaults to now."""
    s = read_state()
    ts = datetime.fromisoformat(cooked_at) if cooked_at else _now()
    s.ratings.append(Rating(
        recipe_title=recipe_title, rater=rater, rating=rating, cooked_at=ts,
    ))
    s.last_updated = _now()
    save_json("state.json", s)
    return s


_SNAPSHOT: State | None = None


def snapshot_for_undo() -> None:
    """Capture current state for a one-step undo. Called before any mutation."""
    global _SNAPSHOT
    _SNAPSHOT = read_state().model_copy(deep=True)


def restore_snapshot() -> State | None:
    """Restore the most recent snapshot. Returns the restored state or None."""
    global _SNAPSHOT
    if _SNAPSHOT is None:
        return None
    save_json("state.json", _SNAPSHOT)
    restored = _SNAPSHOT
    _SNAPSHOT = None
    return restored
```

- [ ] **Step 2: Sanity check**

Run: `python -c "from tools.state import read_state; print(read_state().model_dump())"`
Expected: JSON-like dict with empty plan, empty pantry, empty ratings. A `state/state.json` file should be created.

Clean up: `rm -rf state/`

- [ ] **Step 3: Commit**

```bash
git add tools/state.py
git commit -m "feat: state read/mutation tools with undo snapshot"
```

---

### Task 8: Prompts

**Files:**
- Create: `agents/prompts.py`

- [ ] **Step 1: Implement `agents/prompts.py`**

```python
# agents/prompts.py

ORCHESTRATOR_SYSTEM_PROMPT = """You are the meal-planning assistant for a household.

HOUSEHOLD CONTEXT (from profile.json, injected per-turn):
{profile_summary}

CURRENT STATE SUMMARY:
{state_summary}

TODAY: {today}

YOUR JOB:
- Plan Mon–Fri dinners on request.
- Edit the plan on natural-language requests from the user.
- Check pantry, suggest swaps, record ratings.
- Default: plan from your own knowledge. Pull from recipes.json when
  the user references past meals or asks "what have we liked recently".
- Web search ONLY when the user explicitly asks to find/discover new
  recipes or "update the database". Use the find_new_recipes tool.

HARD RULES (enforced by validate_plan — surface warnings, don't self-heal):
- >=1 fish meal per week
- Every meal includes a vegetable
- Never schedule a recipe both adults rated never_again
- Never schedule anything in household_dislikes

SOFT PREFERENCES (use judgement):
- Favor recipes rated 'again_soon' or 'worth_repeating'
- Favor pantry-aligned recipes (ingredients already in stock)
- Include 1-2 recipes requiring shopping - keep it interesting
- Avoid repeating a recipe cooked in the last 7 days

INTERACTION RULES:
- Always confirm before calling update_plan / update_pantry / update_profile
  unless the user said "just do it"
- After any update_plan, call validate_plan and surface warnings verbatim
- Keep responses short. The user reads the table, not prose.
- If profile.json is empty (first run), open with an onboarding chat to learn
  about the household before doing anything else.
"""


RECIPE_FINDER_SYSTEM_PROMPT = """You are a recipe researcher. Given a query and household context:
1. Use web_search to find 3-5 recipes matching the query.
2. Prefer reputable recipe sites (BBC Good Food, Serious Eats, NYT Cooking,
   Bon Appetit, Food Network).
3. For each: extract title, cuisine, main_protein, key_ingredients (5-8 items),
   cook_time_min, source_url.
4. Return a JSON array where each element matches this shape:
   {{"title": str, "cuisine": str, "main_protein": str,
     "key_ingredients": [str], "tags": [str], "cook_time_min": int,
     "source_url": str}}
5. Filter against the household context provided - do not return anything
   that violates dislikes or dietary rules.

Query: {query}
Count requested: {count}
Household context:
{household_context}
"""
```

- [ ] **Step 2: Commit**

```bash
git add agents/prompts.py
git commit -m "feat: system prompts for orchestrator + recipe finder"
```

---

### Task 9: RecipeFinder subagent

**Files:**
- Create: `agents/recipe_finder.py`

This is a separate Anthropic client call with `web_search_20250305` as a tool. Returns parsed Recipe objects.

- [ ] **Step 1: Implement `agents/recipe_finder.py`**

```python
# agents/recipe_finder.py
import json
import re
from datetime import datetime
from anthropic import Anthropic
from models import Recipe, Profile
from agents.prompts import RECIPE_FINDER_SYSTEM_PROMPT

MODEL = "claude-sonnet-4-6"


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "untitled"


def _household_context(profile: Profile | None) -> str:
    if profile is None:
        return "(no household profile set yet)"
    dislikes = ", ".join(profile.household_dislikes) or "none"
    rules = "; ".join(profile.dietary_rules) or "none"
    cuisines = ", ".join(profile.preferred_cuisines) or "no preference"
    return (
        f"Household dislikes: {dislikes}\n"
        f"Dietary rules: {rules}\n"
        f"Preferred cuisines: {cuisines}\n"
    )


def find_new_recipes(query: str, count: int, profile: Profile | None) -> list[Recipe]:
    """Run an isolated Claude session with web_search, return structured recipes."""
    client = Anthropic()
    system_prompt = RECIPE_FINDER_SYSTEM_PROMPT.format(
        query=query,
        count=count,
        household_context=_household_context(profile),
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system_prompt,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }],
        messages=[{
            "role": "user",
            "content": f"Find {count} recipes for: {query}",
        }],
    )
    # Extract the final assistant text — the last text block after web_search turns
    text_parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
    raw = "\n".join(text_parts).strip()

    # Pull the JSON array out of the response
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

- [ ] **Step 2: Sanity check (optional, requires API key)**

With `ANTHROPIC_API_KEY` set:
```
python -c "from agents.recipe_finder import find_new_recipes; import json; print(json.dumps([r.model_dump(mode='json') for r in find_new_recipes('Portuguese bacalhau', 3, None)], indent=2, default=str))"
```
Expected: 2–3 recipes with `source_url` populated.

If API key not yet set, skip this step.

- [ ] **Step 3: Commit**

```bash
git add agents/recipe_finder.py
git commit -m "feat: RecipeFinder subagent with web search"
```

---

### Task 10: Complete `tools/recipes.py` with `find_new_recipes` wiring + persistence

**Files:**
- Modify: `tools/recipes.py` (append to file from Task 5)

- [ ] **Step 1: Add to `tools/recipes.py`**

Append after the existing code:

```python
# --- Persistence + subagent wiring ---

from datetime import datetime
from storage import load_json_list, save_json_list
from models import Recipe as _Recipe, Profile as _Profile


def load_all_recipes() -> list[_Recipe]:
    """Load every saved recipe from recipes.json (returns [] if missing)."""
    return load_json_list("recipes.json", _Recipe)


def save_all_recipes(recipes: list[_Recipe]) -> None:
    save_json_list("recipes.json", recipes)


def get_recipe(recipe_id: str) -> dict | None:
    """Return the full recipe as a dict, or None if not found."""
    for r in load_all_recipes():
        if r.id == recipe_id:
            return r.model_dump(mode="json")
    return None


def append_recipes(new: list[_Recipe]) -> list[_Recipe]:
    """Append new recipes, skipping duplicates by id. Returns the newly added."""
    existing = load_all_recipes()
    existing_ids = {r.id for r in existing}
    added: list[_Recipe] = []
    for r in new:
        if r.id in existing_ids:
            continue
        existing.append(r)
        added.append(r)
        existing_ids.add(r.id)
    save_all_recipes(existing)
    return added


def find_new_recipes_tool(query: str, count: int, profile: _Profile | None) -> list[dict]:
    """Tool-facing: spawn subagent, append results to recipes.json, return summaries."""
    from agents.recipe_finder import find_new_recipes  # local import avoids cycle
    found = find_new_recipes(query, count, profile)
    added = append_recipes(found)
    return [recipe_summary(r) for r in added]
```

- [ ] **Step 2: Smoke test the imports**

Run: `python -c "from tools.recipes import load_all_recipes, get_recipe, find_new_recipes_tool, list_recipes, search_recipes; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add tools/recipes.py
git commit -m "feat: wire find_new_recipes tool + recipe persistence"
```

---

### Task 11: Orchestrator agent loop

**Files:**
- Create: `agents/orchestrator.py`

Wraps the Anthropic tool-use loop. Exposes a single `run_turn(user_message, history) -> (assistant_text, updated_history)` function for the Streamlit layer.

- [ ] **Step 1: Implement `agents/orchestrator.py`**

```python
# agents/orchestrator.py
import json
from datetime import datetime
from anthropic import Anthropic
from agents.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from tools.profile import read_profile, update_profile
from tools.state import (
    read_state, update_plan, update_pantry, record_rating,
    snapshot_for_undo, restore_snapshot,
)
from tools.recipes import (
    load_all_recipes, list_recipes, search_recipes, get_recipe,
    find_new_recipes_tool,
)
from tools.validate import validate_plan
from models import MealPlanSlot

MODEL = "claude-sonnet-4-6"
MAX_TOOL_ITERATIONS = 15


# --- Tool schema (what Claude sees) ---

TOOL_DEFINITIONS = [
    {
        "name": "read_profile",
        "description": "Read the household profile (members, dislikes, dietary rules).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_profile",
        "description": "Create or merge-update the household profile. Pass any subset of fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "household_size": {"type": "integer"},
                "members": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "is_adult": {"type": "boolean"},
                            "dislikes": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name", "is_adult"],
                    },
                },
                "household_dislikes": {"type": "array", "items": {"type": "string"}},
                "dietary_rules": {"type": "array", "items": {"type": "string"}},
                "preferred_cuisines": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "read_state",
        "description": "Read the current meal plan, pantry, and ratings.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_plan",
        "description": "Replace the meal_plan wholesale. Provide 5 slots (Mon-Fri).",
        "input_schema": {
            "type": "object",
            "properties": {
                "slots": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "string", "enum": ["Mon","Tue","Wed","Thu","Fri"]},
                            "recipe_title": {"type": "string"},
                            "recipe_id": {"type": ["string", "null"]},
                            "key_ingredients": {"type": "array", "items": {"type": "string"}},
                            "rationale": {"type": "string"},
                        },
                        "required": ["day", "recipe_title", "key_ingredients", "rationale"],
                    },
                },
            },
            "required": ["slots"],
        },
    },
    {
        "name": "update_pantry",
        "description": "Add/remove perishables in the pantry. In/out only (no quantities).",
        "input_schema": {
            "type": "object",
            "properties": {
                "add": {"type": "array", "items": {"type": "string"}},
                "remove": {"type": "array", "items": {"type": "string"}},
            },
            "required": [],
        },
    },
    {
        "name": "record_rating",
        "description": "Record a rating for a cooked meal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipe_title": {"type": "string"},
                "rater": {"type": "string"},
                "rating": {"type": "string",
                           "enum": ["again_soon", "worth_repeating", "meh", "never_again"]},
            },
            "required": ["recipe_title", "rater", "rating"],
        },
    },
    {
        "name": "list_recipes",
        "description": "List saved recipes as compact summaries. Optional exact-match filters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filters": {"type": "object"},
            },
            "required": [],
        },
    },
    {
        "name": "get_recipe",
        "description": "Fetch full details for one recipe by id.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "search_recipes",
        "description": "Keyword search over saved recipes. Ranks by match count, then rating, then times_cooked.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "filters": {"type": "object"},
                "top_k": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_new_recipes",
        "description": "Spawn a web-search subagent to discover new recipes. Use ONLY when the user explicitly asks to find/discover or update the recipe database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "count": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "validate_plan",
        "description": "Check the current saved plan against hard rules. Returns a list of warnings (empty = OK).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "undo",
        "description": "Restore the state snapshot taken at the start of this turn.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


# --- Tool dispatcher ---

def _dispatch(name: str, args: dict) -> str:
    """Run a tool and return a JSON-serialisable string result for the agent."""
    try:
        if name == "read_profile":
            p = read_profile()
            return json.dumps(p.model_dump(mode="json") if p else None)
        if name == "update_profile":
            snapshot_for_undo()
            return json.dumps(update_profile(args).model_dump(mode="json"))
        if name == "read_state":
            return json.dumps(read_state().model_dump(mode="json"))
        if name == "update_plan":
            snapshot_for_undo()
            return json.dumps(update_plan(args["slots"]).model_dump(mode="json"))
        if name == "update_pantry":
            snapshot_for_undo()
            return json.dumps(update_pantry(
                add=args.get("add", []), remove=args.get("remove", [])
            ).model_dump(mode="json"))
        if name == "record_rating":
            snapshot_for_undo()
            return json.dumps(record_rating(
                recipe_title=args["recipe_title"],
                rater=args["rater"],
                rating=args["rating"],
            ).model_dump(mode="json"))
        if name == "list_recipes":
            return json.dumps(list_recipes(load_all_recipes(), filters=args.get("filters")))
        if name == "get_recipe":
            return json.dumps(get_recipe(args["id"]))
        if name == "search_recipes":
            return json.dumps(search_recipes(
                load_all_recipes(),
                query=args["query"],
                filters=args.get("filters"),
                top_k=args.get("top_k", 20),
            ))
        if name == "find_new_recipes":
            return json.dumps(find_new_recipes_tool(
                query=args["query"],
                count=args.get("count", 3),
                profile=read_profile(),
            ))
        if name == "validate_plan":
            state = read_state()
            profile = read_profile()
            if profile is None:
                return json.dumps(["No profile set yet — skipping validation."])
            return json.dumps(validate_plan(state.meal_plan, profile, state.ratings))
        if name == "undo":
            restored = restore_snapshot()
            return json.dumps({"ok": restored is not None})
        return json.dumps({"error": f"unknown tool: {name}"})
    except Exception as exc:  # surface errors back to the agent, don't crash the session
        return json.dumps({"error": str(exc)})


# --- Per-turn system prompt assembly ---

def _profile_summary() -> str:
    p = read_profile()
    if p is None:
        return "(empty — no profile yet; onboard the user before planning)"
    members = ", ".join(f"{m.name}{'*' if m.is_adult else ''}" for m in p.members)
    return (
        f"Size: {p.household_size}; Members: {members} (* = adult); "
        f"Household dislikes: {p.household_dislikes or 'none'}; "
        f"Dietary rules: {p.dietary_rules or 'none'}; "
        f"Preferred cuisines: {p.preferred_cuisines or 'none'}; "
        f"Notes: {p.notes or 'none'}"
    )


def _state_summary() -> str:
    s = read_state()
    plan_line = (
        " | ".join(f"{slot.day}: {slot.recipe_title}" for slot in s.meal_plan)
        if s.meal_plan else "(no plan set)"
    )
    pantry = ", ".join(s.pantry) if s.pantry else "(empty)"
    n_ratings = len(s.ratings)
    return f"Plan: {plan_line}\nPantry: {pantry}\nRatings recorded: {n_ratings}"


def _build_system_prompt() -> str:
    return ORCHESTRATOR_SYSTEM_PROMPT.format(
        profile_summary=_profile_summary(),
        state_summary=_state_summary(),
        today=datetime.now().strftime("%A %Y-%m-%d"),
    )


# --- Public API ---

def run_turn(user_message: str, history: list[dict]) -> tuple[str, list[dict]]:
    """Run one conversational turn. Returns (assistant text, updated history).

    history is a list of {role, content} dicts in the Anthropic Messages API shape.
    """
    client = Anthropic()
    messages = history + [{"role": "user", "content": user_message}]
    system = _build_system_prompt()

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            text_parts = [b.text for b in response.content if b.type == "text"]
            return ("\n".join(text_parts).strip(), messages)

        # Run every tool call in the response, append results as one user turn
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _dispatch(block.name, block.input or {})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        messages.append({"role": "user", "content": tool_results})

    return ("(tool loop limit hit — simplify your request)", messages)
```

- [ ] **Step 2: Smoke test imports**

Run: `python -c "from agents.orchestrator import run_turn, TOOL_DEFINITIONS; print(len(TOOL_DEFINITIONS), 'tools defined')"`
Expected: `12 tools defined`.

- [ ] **Step 3: Commit**

```bash
git add agents/orchestrator.py
git commit -m "feat: orchestrator agent loop with tool dispatch"
```

---

### Task 12: Streamlit UI

**Files:**
- Create: `app.py`

- [ ] **Step 1: Implement `app.py`**

```python
# app.py
import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from tools.state import read_state
from tools.profile import read_profile
from agents.orchestrator import run_turn

st.set_page_config(page_title="Meal Planner (Agentic)", layout="wide")
st.title("Meal Planner")

if not os.getenv("ANTHROPIC_API_KEY"):
    st.error("ANTHROPIC_API_KEY not set. Add it to .env and restart.")
    st.stop()

# --- Session state ---
if "history" not in st.session_state:
    st.session_state.history = []  # list[{"role": "user"|"assistant", "content": ...}]
if "chat_display" not in st.session_state:
    st.session_state.chat_display = []  # list[{"role", "text"}] for rendering


def _render_plan_table():
    s = read_state()
    if not s.meal_plan:
        st.info("No meal plan yet. Ask the agent to plan next week.")
        return
    rows = [{
        "Day": slot.day,
        "Recipe": slot.recipe_title,
        "Protein": slot.key_ingredients[0] if slot.key_ingredients else "",
        "Key ingredients": ", ".join(slot.key_ingredients),
        "Why": slot.rationale,
    } for slot in s.meal_plan]
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
            st.write(" · ".join(s.pantry))
        else:
            st.caption("(empty)")

        with st.expander("Recent ratings"):
            if not s.ratings:
                st.caption("(none)")
            else:
                for r in s.ratings[-10:]:
                    st.caption(f"{r.cooked_at.date()} · {r.rater}: {r.recipe_title} → {r.rating}")


# --- Layout ---
_render_sidebar()
st.subheader("This week")
_render_plan_table()
st.divider()
st.subheader("Chat")

for msg in st.session_state.chat_display:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])

user_input = st.chat_input("Tell the agent what you want…")
if user_input:
    st.session_state.chat_display.append({"role": "user", "text": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            reply, new_history = run_turn(user_input, st.session_state.history)
        st.session_state.history = new_history
        st.session_state.chat_display.append({"role": "assistant", "text": reply})
        st.markdown(reply)
    st.rerun()  # refresh table + sidebar to reflect any state changes
```

- [ ] **Step 2: Smoke run (with API key)**

Run: `streamlit run app.py`
Open the printed URL. Verify:
- Empty state renders (no plan, no pantry).
- Typing "Hi, onboard me" kicks off an onboarding conversation.
- After providing household info, ask: "plan next week" → table populates.
- Ask: "swap Wednesday for something lighter" → table updates.

Kill the server when satisfied.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: Streamlit UI — chat + meal plan table + sidebar"
```

---

### Task 13: Update README with usage

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite `README.md`**

```markdown
# Meal Planner (Agentic)

Chat-driven weekly dinner planner. Talk to an agent; it maintains your meal plan, pantry, and recipe library as JSON files.

See [design spec](docs/superpowers/specs/2026-04-15-meal-planner-agentic-design.md).

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env   # fill ANTHROPIC_API_KEY
streamlit run app.py   # → http://localhost:8501
```

## What it does

- Plans Mon–Fri dinners from the agent's own knowledge
- Edits the plan via natural language ("swap Wednesday for something lighter")
- Tracks pantry, ratings, and dislikes in three JSON files under `state/`
- Web search only on explicit request ("find me 3 Portuguese bacalhau recipes")
- Warns when the plan violates hard rules (≥1 fish/week, veg every meal, etc.)

## State files

| File | Purpose |
|---|---|
| `state/profile.json` | Household (members, dislikes, dietary rules) |
| `state/recipes.json` | Saved recipes (grows on web search) |
| `state/state.json` | Current plan + pantry + ratings |

Delete any of these to reset that slice of state.

## Tests

```bash
pytest -v
```

Covers: validator rules, storage round-trips, search ranking, model serialization.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with setup + usage"
```

---

### Task 14: Full-stack smoke test & polish

**Files:**
- None modified unless bugs surface.

- [ ] **Step 1: Fresh-state end-to-end run**

```
rm -rf state/
streamlit run app.py
```

Walk through:
1. First turn: "Hi, onboard me" — verify agent collects household info and calls `update_profile`.
2. "Plan next week" — table renders 5 slots.
3. Check `state/state.json` on disk matches what's shown.
4. "Swap Thu for tofu" — table updates, state file reflects the change.
5. "We just had salmon teriyaki, Ana says again_soon" — rating recorded.
6. "Find me 3 Portuguese bacalhau recipes" — web search runs, `state/recipes.json` has new entries (may take 15–30s).
7. "What have we liked recently?" — agent uses `search_recipes` / `list_recipes` with rating filter.
8. "Undo that last change" — verify state reverts.

- [ ] **Step 2: Run full test suite**

Run: `pytest -v`
Expected: all tests from Tasks 2–5 pass.

- [ ] **Step 3: Commit any fixes**

If the smoke run surfaced bugs, fix them with minimal changes and commit individually.

- [ ] **Step 4: Final commit (if no fixes needed)**

```bash
# No-op if nothing changed. Otherwise, commit fixes with descriptive messages.
git log --oneline -15   # sanity check commit history
```

---

## Self-review notes

**Spec coverage check:**
- §3 Architecture — Tasks 1, 9, 11, 12 ✓
- §4 Data model — Task 2 ✓
- §5 Tools (all 11) — Tasks 5, 6, 7, 10, 11 ✓
- §6 Prompts — Task 8 ✓
- §7 UI — Task 12 ✓
- §8 Validator — Task 4 ✓
- §9 Model routing — Tasks 9, 11 (Sonnet constant) ✓
- §10 Project layout — Task 1 ✓
- §11 Dependencies — Task 1 ✓
- §12 Running it — Task 13 (README) ✓
- §13 Testing scope — Tasks 2, 3, 4, 5 ✓

**Open items from spec §14:**
- Subagent API shape — resolved in Task 9 (raw Anthropic tool-use with `web_search_20250305`)
- Sync vs streaming `find_new_recipes` — Task 9 starts sync; revisit post-smoke if latency is painful
- Undo depth — Task 7 implements single-step per turn; multi-step deferred
