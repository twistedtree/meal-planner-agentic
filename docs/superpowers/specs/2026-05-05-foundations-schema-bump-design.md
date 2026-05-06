# Foundations: household_id + State Schema Bump — Design

**Status:** Draft v1
**Date:** 2026-05-05
**Sub-project of:** `meal-planner-agentic`
**Predecessor sub-project:** `2026-05-03-edit-recipes-and-tracing-design.md`
**Successor sub-projects (planned, not in scope here):** capability 10 (calendar), capability 11 (pantry expiry), capability 12 (grocery list), capability 13 (tonight mode), capability 14 (receipt-paste), Cookidoo timeout fix.

---

## 1. Goal & scope

This sub-project is a foundation pass: a schema bump and backwards-compatible loaders that unblock capabilities 11 and 13 from the BRD roadmap. It ships **no user-visible behaviour changes** beyond the orchestrator's tool surface accepting richer pantry inputs.

### A. Schema changes

1. Add `household_id: str = "default"` to `Profile` and `State`. Invisible in UI per design assessment; sole purpose is multi-household scoping if a second household ever onboards.
2. Promote `State.pantry: list[str]` to `State.pantry: list[PantryItem]` where `PantryItem = {name, quantity?, expiry_at?}`.
3. Add `State.tonight_history: list[OneOffMeal]`, capped at 30 entries on write, where `OneOffMeal = {recipe_title, cooked_at, members, time_min}`.
4. Add new Pydantic models `PantryItem` and `OneOffMeal` to `models.py`.

### B. Backwards-compat loaders

Existing `state/profile.json` and `state/state.json` files must load without manual intervention. Concretely:

- `Profile.household_id` and `State.household_id` get a Pydantic `Field(default="default")` so missing-on-disk entries are filled at validation time.
- `State.pantry` keeps the old `list[str]` shape valid via a Pydantic field validator that coerces any bare string `s` into `PantryItem(name=s, quantity=None, expiry_at=None)`.
- `State.tonight_history` defaults to `[]` via `Field(default_factory=list)`.

### C. Tool surface adjustments

- `update_pantry(add: list[str | dict], remove: list[str])`: the `add` parameter accepts heterogeneous entries. Bare strings are coerced. Dict entries flow through to `PantryItem`.
- `read_state` and the orchestrator's `state_summary` render pantry items in compact form: `name (Q, expires YYYY-MM-DD)` when quantity / expiry are set, otherwise just `name`. The change costs ~10 to 30 prompt tokens at typical pantry sizes.
- Orchestrator system prompt picks up two new lines: one telling the agent how to pass quantity / expiry through `update_pantry` (just the schema, not behavioural rules), and one noting that bare-string pantry entries are still acceptable when no quantity / expiry is known.

### D. Migration script

`scripts/migrate_state_schema_2026_05_05.py`: opens `state/*.json`, runs them through the new Pydantic models, writes back. Idempotent (running twice is a no-op). Optional — Pydantic validators handle live loads fine; the script is for users who want their files visibly normalised on disk.

### Out of scope

- Capability 11 (expiry-aware planning, default-expiry keyword table, sidebar pills). Schema only here; planning logic lands in the next sub-project.
- Capability 13 (`plan_tonight`, `record_one_off_meal` tool, scoring). Schema only here; the `tonight_history` array gets created and stays empty.
- Calendar tool, grocery list, receipt parsing.
- UI surface for `household_id`. Stays invisible.
- Multi-household scoping logic (filtering by `household_id` at read/write). Field is added; nothing reads it yet.
- Pantry quantity arithmetic (parsing "250g" + "300g" → "550g"). Quantities are free-text strings.
- Postgres / database migration. JSON files stay the source of truth.

---

## 2. Schema changes (concrete)

### `models.py` additions

```python
from datetime import datetime, date
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class PantryItem(BaseModel):
    name: str
    quantity: str | None = None       # free-text: "250g", "1 bag", "half jar"
    expiry_at: date | None = None     # set by user or by category-default lookup (cap 11)


class OneOffMeal(BaseModel):
    recipe_title: str
    cooked_at: datetime
    members: list[str] = Field(default_factory=list)
    time_min: int | None = None
```

### `models.Profile` change

```python
class Profile(BaseModel):
    household_id: str = "default"     # NEW
    household_size: int
    members: list[Member]
    household_dislikes: list[str] = Field(default_factory=list)
    dietary_rules: list[str] = Field(default_factory=list)
    preferred_cuisines: list[str] = Field(default_factory=list)
    notes: str = ""
```

### `models.State` change

```python
class State(BaseModel):
    household_id: str = "default"                 # NEW
    meal_plan: list[MealPlanSlot] = Field(default_factory=list)
    week_of: date | None = None
    plan_history: list[ArchivedPlan] = Field(default_factory=list)
    pantry: list[PantryItem] = Field(default_factory=list)   # CHANGED type
    ratings: list[Rating] = Field(default_factory=list)
    tonight_history: list[OneOffMeal] = Field(default_factory=list)  # NEW
    last_updated: datetime

    @field_validator("pantry", mode="before")
    @classmethod
    def _coerce_legacy_pantry(cls, v):
        """Coerce bare-string pantry entries (legacy shape) to PantryItem dicts."""
        if not isinstance(v, list):
            return v
        return [
            {"name": x} if isinstance(x, str) else x
            for x in v
        ]
```

### File-on-disk shape after the bump

```jsonc
// state/profile.json
{
  "household_id": "default",
  "household_size": 4,
  "members": [...],
  ...
}

// state/state.json
{
  "household_id": "default",
  "meal_plan": [...],
  "pantry": [
    {"name": "rice", "quantity": null, "expiry_at": null},
    {"name": "salmon", "quantity": "280g", "expiry_at": "2026-05-07"}
  ],
  "tonight_history": [],
  ...
}
```

A bare-string pantry on disk (`["rice", "salmon"]`) loads unchanged in memory; `save_json` writes it back in the new dict shape. After the next save, the file is normalised. Migration is therefore lazy (next save normalises) plus optional script for impatient users.

---

## 3. Tool surface adjustments

### `tools/state.update_pantry`

Signature changes from `(add: list[str], remove: list[str])` to:

```python
def update_pantry(
    add: list[str | dict] | None = None,
    remove: list[str] | None = None,
) -> State:
    """Apply a diff to the pantry.

    `add` accepts:
      - bare strings: 'salmon' → PantryItem(name='salmon')
      - dicts: {'name': 'salmon', 'quantity': '280g', 'expiry_at': '2026-05-07'}

    `remove` is a list of names; case-insensitive exact match on PantryItem.name.
    Duplicate names dedupe by name (latest add wins for quantity / expiry_at).
    """
```

Internal normalisation: every entry coerced to `PantryItem` before dedupe. Dedupe key is `name.lower().strip()`. On collision, the newer add overwrites quantity / expiry_at if those are non-None.

### Orchestrator tool schema (`agents/orchestrator.TOOL_DEFINITIONS`)

`update_pantry` schema becomes:

```python
_tool("update_pantry",
      "Add/remove perishables in the pantry. Items can be bare names or "
      "objects with optional quantity (free text) and expiry_at (YYYY-MM-DD).",
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
                                  "expiry_at": {"type": ["string", "null"],
                                                "description": "ISO date YYYY-MM-DD"},
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

### Orchestrator `_state_summary`

Pantry rendering changes from:

```
Pantry: rice, salmon, tinned tomatoes
```

to (mixed example):

```
Pantry: rice, salmon (280g, exp 2026-05-07), tinned tomatoes
```

Implementation: `", ".join(_render_item(p) for p in s.pantry)` where `_render_item` formats `name` plus optional ` (q)`, ` (exp d)`, or ` (q, exp d)` depending on which optional fields are set.

### Orchestrator system prompt addition

Add a short bullet to the existing TOOL EFFICIENCY section:

> The pantry is a list of items, each of which has a name, an optional free-text quantity (e.g. "250g", "1 bag"), and an optional expiry date (ISO YYYY-MM-DD). When the user mentions a quantity or expiry date, pass it through `update_pantry` as a dict; otherwise a bare name string is fine.

No behavioural rules tied to expiry yet (those land in capability 11).

---

## 4. Migration script

`scripts/migrate_state_schema_2026_05_05.py`:

```python
"""Idempotent: normalises state/*.json files to the 2026-05-05 schema.

Optional. Pydantic validators handle legacy files at runtime; this script just
makes the on-disk files visibly current.
"""
from pathlib import Path
from models import Profile, State
from storage import STATE_DIR, save_json

def main() -> None:
    profile_path = STATE_DIR / "profile.json"
    if profile_path.exists():
        p = Profile.model_validate_json(profile_path.read_text(encoding="utf-8"))
        save_json("profile.json", p)
        print(f"normalised {profile_path}")

    state_path = STATE_DIR / "state.json"
    if state_path.exists():
        s = State.model_validate_json(state_path.read_text(encoding="utf-8"))
        save_json("state.json", s)
        print(f"normalised {state_path}")

    print("done")

if __name__ == "__main__":
    main()
```

Run with `uv run python scripts/migrate_state_schema_2026_05_05.py`. No-op if the schema is already current. Recipes are unaffected (no schema change).

---

## 5. Tests

All unit tests, no eval impact. New file:

`tests/test_state_schema_2026_05_05.py`:

- `test_profile_loads_legacy_without_household_id`: write a `profile.json` without `household_id`; load → `household_id == "default"`.
- `test_state_loads_legacy_without_household_id`: same for `State`.
- `test_state_loads_legacy_pantry_strings`: write a `state.json` with `pantry: ["rice", "salmon"]`; load → `pantry == [PantryItem(name="rice"), PantryItem(name="salmon")]`.
- `test_state_loads_mixed_pantry`: pantry on disk has both shapes; both load correctly.
- `test_pantry_round_trip_normalises_to_dicts`: load legacy → save → reload → bytes-on-disk show dict shape.
- `test_tonight_history_defaults_empty`: load legacy `state.json` → `tonight_history == []`.
- `test_update_pantry_accepts_bare_string`: `update_pantry(add=["rice"])` → pantry contains `PantryItem(name="rice")`.
- `test_update_pantry_accepts_dict`: `update_pantry(add=[{"name": "salmon", "quantity": "280g", "expiry_at": "2026-05-07"}])` → pantry contains the full item.
- `test_update_pantry_dedupe_overwrites_quantity`: add "rice" then add `{"name": "rice", "quantity": "1 bag"}` → single entry with quantity set.
- `test_update_pantry_remove_case_insensitive`: add "Salmon", remove "salmon" → empty.
- `test_pantry_dict_dedupe_keeps_later_expiry`: add `{name: salmon, expiry_at: 2026-05-07}` then `{name: salmon, expiry_at: 2026-05-09}` → expiry is the latest.
- `test_state_summary_renders_quantity_and_expiry`: import `_state_summary`; assert it renders the new pantry shape correctly when quantity / expiry are set, and falls back to bare name otherwise.
- `test_migration_script_is_idempotent`: run migration twice; second run produces byte-identical files.

Existing `test_state.py` and `test_storage.py` get updated where they assert pantry shape. Most assertions today are on `pantry` membership (substring / exact name) which keeps working unchanged once names are read from `PantryItem.name`.

No eval changes. The eval fixtures (`tests/evals/fixtures/*.json`) keep their current shape; Pydantic coerces them on load.

---

## 6. Project layout after this sub-project

```
meal-planner-agentic/
  models.py                                          # +PantryItem, +OneOffMeal, +household_id, +tonight_history, +pantry validator
  agents/
    orchestrator.py                                  # update_pantry tool schema; _state_summary rendering
    prompts.py                                       # short pantry shape note
  tools/
    state.py                                         # update_pantry signature + dedupe
  scripts/
    migrate_state_schema_2026_05_05.py               # NEW (optional one-shot)
  tests/
    test_state_schema_2026_05_05.py                  # NEW
  docs/
    superpowers/specs/
      2026-05-05-foundations-schema-bump-design.md   # this doc
    superpowers/plans/
      2026-05-05-foundations-schema-bump-plan.md     # next, generated by writing-plans skill
```

No changes to `app.py` (sidebar already calls into existing `read_state`; the rendered pantry pill string falls back to `item.name` once `app.py` is updated to iterate PantryItem objects rather than strings).

Actually one small UI touch: `app.py` line ~71 (`st.write(" · ".join(s.pantry))`) needs to become `st.write(" · ".join(p.name for p in s.pantry))`. Quantity / expiry pills are deferred to capability 11.

---

## 7. Risks & open items

- **Tool-schema `anyOf` and OpenRouter routing.** The new `update_pantry.add` schema uses `anyOf` to accept string or object. LiteLLM passes JSON Schema through to the upstream provider; some providers may reject `anyOf` items. Mitigation: if it breaks, downgrade to `{"type": "object"}` only (force the agent to wrap bare names) and update the prompt to compensate. Tested first against `claude-sonnet-4.5`; if good, no change needed.
- **Prompt context growth.** Pantry rendering grows per-item by ~5 to 25 chars when quantity / expiry are set. Tracked via tracing summary; revisit if turn-prompt token median rises >5%.
- **`field_validator` ordering.** `mode="before"` is required so the coercion runs before Pydantic tries to validate the list as `list[PantryItem]`. Verified by the load-legacy unit tests.
- **Date parsing for `expiry_at`.** Pydantic auto-parses ISO date strings into `date`. The agent gets explicit "YYYY-MM-DD" guidance in the tool description; non-ISO dates raise `ValidationError` which surfaces as a turn-level tool error.
- **Recipes file unchanged.** No schema bump for `recipes.json`. If the same household_id rule were applied to recipes (one library per household), it would matter; today recipes are shared across the only household, so deferred.
- **`tonight_history` capped at 30.** Cap enforced on write (in capability 13's `record_one_off_meal`, not here). This sub-project just creates the empty array. Document the cap in the spec but don't enforce yet.
- **Manual smoke vs eval.** No new eval test in this sub-project (it's a schema bump). The existing eval suite must still pass against the new schema. If any eval breaks because pantry rendering changed, fix the assertion.

---

## 8. Implementation order (full plan generated by writing-plans skill next)

1. Add `PantryItem` and `OneOffMeal` to `models.py`.
2. Add `household_id` to `Profile` and `State`. Add `tonight_history` to `State`. Add `pantry` field validator.
3. Update `tools/state.update_pantry` to handle the heterogeneous `add` list, dedupe, and overwrite semantics.
4. Update `agents/orchestrator.TOOL_DEFINITIONS` for the new `update_pantry` schema.
5. Update `agents/orchestrator._state_summary` to render the new pantry shape.
6. Update `agents/prompts.ORCHESTRATOR_SYSTEM_PROMPT` with the short pantry-shape note.
7. Update `app.py` pantry sidebar render to iterate `PantryItem.name`.
8. Add `tests/test_state_schema_2026_05_05.py` with the unit tests listed above.
9. Update existing tests (`test_state.py`, `test_storage.py`) where they assert pantry shape.
10. Add `scripts/migrate_state_schema_2026_05_05.py`.
11. Run `pytest -m "not eval" -v` until green.
12. Run `pytest -m eval -v` to confirm no eval regression from rendering changes.
13. Update `docs/architecture.yaml`, `docs/BUILD_SPEC.md`, `docs/PRD.md` (capabilities 11 and 13 acceptance criteria reference the new schema, but the schema itself is now built; mark in the docs that foundations is done).
14. Bump `BRD.md` roadmap: foundations moves from Planned to Done; capability 11 moves up to "in progress / next sub-project" (or stays Planned if Cookidoo timeout fix is done first).
