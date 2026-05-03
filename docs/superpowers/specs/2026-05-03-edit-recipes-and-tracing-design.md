# Edit Recipes, Tracing & Project-Level Docs — Design

**Status:** Draft v1
**Date:** 2026-05-03
**Sub-project of:** `meal-planner-agentic`
**Predecessor spec:** `2026-04-15-meal-planner-agentic-design.md` (the original v1 design — kept for historical context)
**Successor sub-projects (planned, not in scope here):** Cookidoo timeout fix, Cozi integration, Cookidoo grocery-list flow.

---

## 1. Goal & scope

This sub-project does two things:

### A. Establish project-level living docs

Promote the single one-shot design doc into a living set:

- `docs/BRD.md` — Business Requirements Document. Why this app exists, who it serves, success criteria, business-level non-goals.
- `docs/PRD.md` — Product Requirements Document. What the app does today + capabilities. Updated per sub-project.
- `docs/BUILD_SPEC.md` — Build spec. The actual current state: every module, every tool exposed to the orchestrator, every JSON state file, every external integration. Updated on every PR.
- `docs/architecture.yaml` — machine-readable architecture. Source of truth for the build spec; treated as data so future tooling (or the agent itself) can introspect.
- The existing `docs/superpowers/specs/2026-04-15-meal-planner-agentic-design.md` stays as historical context. New per-sub-project specs live in the same folder, dated, and reference (don't duplicate) the BRD/PRD/build-spec.

### B. Three feature additions

1. **Recipe editing via chat** — `update_recipe` and `delete_recipe` tools. All `Recipe` fields editable except `id` (frozen at original slug to preserve referential integrity with `meal_plan` and `plan_history`). Confirmation before mutation.
2. **Tiered LLM tracing** — `traces/summary.jsonl` (one line per turn: tokens, latency, tool calls) + `traces/full/<turn_id>.json` (full message list). Sidebar caption shows last-turn tokens + latency.
3. **Test coverage** — both unit tests (deterministic, no LLM, run on every `pytest`) and an eval harness (`pytest -m eval`, real-model). Single-turn capability tests + 2–3 multi-turn workflow smokes. Each eval run appends to `traces/eval_runs.csv`. Hard token ceilings on named workflows; CSV log on everything.

### Out of scope

- Cookidoo timeout fix
- Cozi integration
- Cookidoo grocery-list flow
- Bulk metadata cleanup tool (deferred)
- A UI editor for recipes (deferred — chat-only for now)
- Trace file rotation / size management (deferred until size is a problem)
- Auto-generation of `BUILD_SPEC.md` from `architecture.yaml` (deferred — hand-maintained until drift is observed)

---

## 2. Project-level docs structure

```
docs/
  BRD.md                         # business why; rarely changes
  PRD.md                         # product capabilities; updated per sub-project
  BUILD_SPEC.md                  # current implementation; updated every PR
  architecture.yaml              # machine-readable arch; source of truth for BUILD_SPEC
  superpowers/
    specs/
      2026-04-15-meal-planner-agentic-design.md   # original (historical)
      2026-05-03-edit-recipes-and-tracing-design.md  # this sub-project
```

### `docs/BRD.md` outline

- **Purpose:** a personal weekly-dinner planner for one Australian household.
- **Stakeholders:** one household (Miguel + family).
- **Success criteria:**
  - Any dinner-planning task can be completed via chat in <60s.
  - Recipe library grows over time without bloating context (token use per turn stays roughly flat as `recipes.json` grows).
  - The agent never silently violates household dislikes / dietary rules — `validate_plan` warnings are surfaced verbatim.
- **Business non-goals:** multi-tenant, mobile-native, billing, account management, anything that benefits a non-household user.

### `docs/PRD.md` outline

One section per capability — current state + delta on each sub-project:

- Plan Mon–Fri dinners
- Edit existing plan via chat
- Pantry tracking
- Recipe library (saved + web-discovered + Cookidoo-imported)
- **Recipe editing & deletion** *(new in this sub-project)*
- Hard-rule validation (`validate_plan`)
- Web search subagent
- Cookidoo integration (list collections, fetch recipe → library)
- **Tracing & evals** *(new in this sub-project)*

Per capability: user story, current behaviour, known limitations, planned next.

### `docs/BUILD_SPEC.md` outline

Generated/maintained alongside `architecture.yaml`. Sections:

- **Components** — `app.py`, `agents/orchestrator.py`, `agents/recipe_finder.py`, tools modules, `storage.py`, `models.py`, `tracing.py` (new).
- **Tools exposed to orchestrator** — full table with name, signature, side-effects, source file. Today: 16 tools; after this sub-project: 18 (+`update_recipe`, +`delete_recipe`).
- **State files** (`state/profile.json`, `state/recipes.json`, `state/state.json`) — schema reference, who reads/writes.
- **External services** — OpenRouter (orchestrator + subagent), Cookidoo API (`cookidoo-api` lib), Web search (via `:online` model suffix).
- **Background workers** — recipe-search bg job registry in `orchestrator.py`.
- **Trace artifacts** *(new)* — `traces/` directory format.

Updated by hand initially; if drift becomes a problem, add `scripts/generate_build_spec.py` to render from `architecture.yaml`.

### `docs/architecture.yaml` outline

```yaml
project: meal-planner-agentic
components:
  - id: ui
    file: app.py
    kind: streamlit
    depends_on: [orchestrator, storage_state, storage_profile, tracing]
  - id: orchestrator
    file: agents/orchestrator.py
    kind: agent
    model: openrouter/anthropic/claude-sonnet-4.5
    depends_on:
      [tool.profile, tool.state, tool.recipes, tool.cookidoo, tool.validate,
       recipe_finder, tracing]
  - id: recipe_finder
    file: agents/recipe_finder.py
    kind: subagent
    model: openrouter/google/gemini-2.5-flash:online
    depends_on: [storage_recipes, tracing]
tools:
  - name: read_profile
    module: tools/profile.py
    side_effects: none
  - name: update_profile
    module: tools/profile.py
    side_effects: writes_profile_json
  - name: read_state
    module: tools/state.py
    side_effects: none
  - name: update_plan
    module: tools/state.py
    side_effects: writes_state_json
  - name: update_pantry
    module: tools/state.py
    side_effects: writes_state_json
  - name: record_rating
    module: tools/state.py
    side_effects: writes_state_json
  - name: list_recipes
    module: tools/recipes.py
    side_effects: none
  - name: get_recipe
    module: tools/recipes.py
    side_effects: none
  - name: search_recipes
    module: tools/recipes.py
    side_effects: none
  - name: find_new_recipes
    module: tools/recipes.py
    side_effects: writes_recipes_json
    spawns: recipe_finder
  - name: update_recipe        # NEW
    module: tools/recipes.py
    side_effects: writes_recipes_json
  - name: delete_recipe        # NEW
    module: tools/recipes.py
    side_effects: writes_recipes_json
  - name: list_cookidoo_collections
    module: tools/cookidoo.py
    side_effects: none
  - name: get_cookidoo_collection
    module: tools/cookidoo.py
    side_effects: none
  - name: fetch_cookidoo_recipe
    module: tools/cookidoo.py
    side_effects: writes_recipes_json
  - name: validate_plan
    module: tools/validate.py
    side_effects: none
  - name: undo
    module: agents/orchestrator.py
    side_effects: writes_state_json
  - name: check_search_status
    module: agents/orchestrator.py
    side_effects: none
state_files:
  - path: state/profile.json
    schema: models.Profile
  - path: state/recipes.json
    schema: list[models.Recipe]
  - path: state/state.json
    schema: models.State
external_services:
  - name: openrouter
    used_by: [orchestrator, recipe_finder]
  - name: cookidoo
    used_by: [tool.cookidoo]
  - name: web_search
    used_by: [recipe_finder]
    notes: routed via OpenRouter ':online' model suffix
traces:
  summary: traces/summary.jsonl
  full_dir: traces/full/
  eval_runs: traces/eval_runs.csv
```

The YAML is the source of truth; `BUILD_SPEC.md` is the human-readable rendering. Kept consistent by PR review convention.

---

## 3. Recipe edit & delete

### New tools

Added to `tools/recipes.py`, registered in `orchestrator.py`:

```python
def update_recipe(recipe_id: str, fields: dict) -> dict | None:
    """Merge-update fields on an existing recipe. id is immutable.
    Returns the updated recipe summary, or None if id not found."""

def delete_recipe(recipe_id: str) -> bool:
    """Remove a recipe by id. Returns True if removed, False if not found."""
```

### Editable fields

All `Recipe` fields except `id` and `added_at`:
`title`, `cuisine`, `main_protein`, `key_ingredients`, `tags`, `cook_time_min`, `last_cooked`, `times_cooked`, `avg_rating`, `source_url`, `source`, `notes`.

A new `notes: str = ""` field is added to the `Recipe` model for free-text user comments.

### Tool schemas (orchestrator-facing)

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
                      "title":            {"type": "string"},
                      "cuisine":          {"type": "string"},
                      "main_protein":     {"type": "string"},
                      "key_ingredients":  {"type": "array", "items": {"type": "string"}},
                      "tags":             {"type": "array", "items": {"type": "string"}},
                      "cook_time_min":    {"type": "integer"},
                      "source_url":       {"type": ["string", "null"]},
                      "source":           {"type": "string"},
                      "notes":            {"type": "string"},
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

### Implementation notes

- Both tools acquire `_recipes_lock` (already used by `append_recipes`) for atomicity.
- `update_recipe` validates against the `Recipe` Pydantic model after merge — invalid edits raise `ValidationError`, surfaced to the user via the agent.
- `id` and `added_at` cannot be changed even if passed in `fields` — silently dropped, noted in trace.
- The agent must confirm before calling either, unless the user said "just do it" (consistent with `update_plan` / `update_pantry` policy).

### Prompt addition (orchestrator system prompt)

Add to the existing INTERACTION RULES section:

> When the user asks to edit or correct a recipe ("change the cuisine on X", "the protein for Y is wrong"), call `update_recipe`. When they ask to remove one ("delete the failed cassoulet"), call `delete_recipe`. Always confirm before either, unless the user said "just do it". Before deleting a recipe currently in `meal_plan` or recently in `plan_history`, warn the user.

### Validator interaction

`delete_recipe` does **not** scrub references in `meal_plan` or `plan_history`. `MealPlanSlot.recipe_id` is already `str | None`, so a stale reference is harmless. The agent surfaces a warning if the deletion would orphan a current plan slot.

---

## 4. Tracing

### New module: `tracing.py` (project root, alongside `storage.py`)

```python
def start_turn(user_message: str) -> str:                    # returns turn_id
def record_completion(turn_id, response, latency_ms): ...    # called per LLM call
def record_tool_call(turn_id, name, args, result_chars): ... # called per tool dispatch
def end_turn(turn_id, final_text, messages): ...             # writes summary + full files
def last_turn_summary() -> dict | None                       # for sidebar caption
```

All trace functions are best-effort: wrapped in `try/except`, log on failure, never raise. Tracing failure must not break the chat loop.

### `traces/summary.jsonl` — one JSON object per line

```json
{
  "turn_id": "2026-05-03T19:42:11.328Z-a1b2",
  "timestamp": "2026-05-03T19:42:11.328Z",
  "model": "openrouter/anthropic/claude-sonnet-4.5",
  "user_message_chars": 87,
  "n_llm_calls": 3,
  "prompt_tokens": 4128,
  "completion_tokens": 412,
  "total_tokens": 4540,
  "latency_ms": 6310,
  "tool_calls": [
    {"name": "read_state", "args_digest": "{}", "result_chars": 612, "ms": 4},
    {"name": "search_recipes", "args_digest": "{query:'light weeknight'}", "result_chars": 894, "ms": 7},
    {"name": "update_plan", "args_digest": "{slots:5, week_of:'2026-05-04'}", "result_chars": 41, "ms": 12}
  ],
  "final_text_chars": 218,
  "subagent_calls": []
}
```

`args_digest` is a short canonical string of the args (truncated keys/values) — it's for grep-ability, not exact reconstruction. Use the full file for reconstruction.

### `traces/full/<turn_id>.json` — verbatim message list

System, user, all assistant turns including `tool_calls`, all tool messages. Lets you replay or diff a turn.

### Wiring

In `agents/orchestrator.run_turn`:

- `turn_id = tracing.start_turn(user_message)` at the top.
- After each `completion(...)` call, `tracing.record_completion(turn_id, response, latency_ms)` — reads `response.usage` (LiteLLM exposes it on every response).
- In `_run_one`, wrap `_dispatch` with `tracing.record_tool_call(turn_id, name, args, len(result))`.
- `tracing.end_turn(turn_id, final_text, messages)` after final assistant text (or after iteration limit).

### Subagent traces

`agents/recipe_finder.find_new_recipes` runs its own `completion()`. It writes a sub-trace nested under the parent turn:

- Parent summary: `subagent_calls: [{turn_id, model, prompt_tokens, completion_tokens, latency_ms}]`.
- Full subagent message list: `traces/full/<parent_turn_id>-sub-<n>.json`.

The parent turn is responsible for calling `tracing.attach_subagent(parent_turn_id, sub_turn_id, sub_summary)` after `find_new_recipes_tool` returns.

### Sidebar caption (in `app.py`)

```
Last turn: 4.5K tokens · 6.3s · 3 tools
```

Pulled from `tracing.last_turn_summary()` (reads the last line of `summary.jsonl`). Hidden if no traces yet.

### Privacy / size

- `traces/` is gitignored (consistent with `state/`).
- No automatic rotation in v1. Revisit if `full/` exceeds ~100MB.

### Truncation visibility

The orchestrator already truncates tool results above `MAX_TOOL_RESULT_CHARS = 4000` before adding them to messages. The trace records `result_chars` (true size, pre-truncation) so you can spot when truncation is biting. Eval can later assert no result exceeds this in a critical workflow.

---

## 5. Tests (unit + eval)

### Two test categories, two run modes

```
tests/
  unit/                        # pure, deterministic, no LLM
    test_validate.py           # existing (moved)
    test_storage.py            # existing (moved)
    test_search.py             # existing (moved)
    test_recipes_crud.py       # NEW — update/delete behaviour
    test_tracing.py            # NEW — start/record/end_turn writes correct files
  evals/                       # marked @pytest.mark.eval, real-model
    conftest.py                # fresh state/, captures eval row to traces/eval_runs.csv
    fixtures/
      profile_basic.json
      recipes_seed.json
    test_capabilities.py       # single-turn cases
    test_workflows.py          # multi-turn smokes
```

`pytest -m "not eval"` (default) runs only unit tests — fast, free, deterministic, no API calls.
`pytest -m eval` runs the LLM-driven evals.

### Unit tests (this sub-project adds two files)

**`tests/unit/test_recipes_crud.py`:**
- `update_recipe` merges fields and preserves untouched ones
- `update_recipe` raises `ValidationError` on invalid types
- `update_recipe` silently drops attempts to change `id` or `added_at`
- `update_recipe` returns `None` for unknown id
- `delete_recipe` removes the row and returns `True`
- `delete_recipe` returns `False` for unknown id
- Both are atomic — verified by mocking the file system and asserting the lock is acquired

**`tests/unit/test_tracing.py`:**
- `start_turn` returns a unique id; concurrent calls don't collide
- `record_tool_call` accumulates entries on the in-memory turn
- `end_turn` writes one line to `summary.jsonl` and one file to `full/<id>.json`
- Trace exceptions don't propagate (best-effort)
- `last_turn_summary` returns the most recent entry

### Eval tests (`pytest -m eval`)

#### Capability tests (`test_capabilities.py`) — one user message against fresh state

| Test | Setup | User message | Asserts |
|---|---|---|---|
| `test_edit_recipe_changes_cuisine` | seed 1 recipe with `cuisine="unknown"` | "change the cuisine on $title to Japanese" | `update_recipe` called with `{cuisine: "japanese"}`; recipe in file has `cuisine="japanese"`; tokens ≤ 4K |
| `test_delete_recipe_removes_row` | seed 2 recipes | "delete $title" | `delete_recipe` called; recipe gone from file; tokens ≤ 3K |
| `test_validate_runs_after_plan_update` | seed profile | "plan next week" | tool order includes `update_plan` → `validate_plan`; tokens ≤ 25K |
| `test_search_before_update_plan` | seed 5 rated recipes | "swap Wednesday for something we've liked" | `search_recipes` called before `update_plan`; tokens ≤ 12K |
| `test_no_web_search_unless_asked` | normal seed | "plan next week" | `find_new_recipes` NOT called |
| `test_web_search_when_asked` | normal seed | "find me 3 Portuguese bacalhau recipes" | `find_new_recipes` called once with sensible query; tokens ≤ 30K |

#### Workflow smokes (`test_workflows.py`) — 2–3 multi-turn scripted conversations

1. **`test_onboard_then_plan`**: empty state → "I'm a household of 4, kids dislike mushrooms" → assert `update_profile` → "plan next week" → assert `update_plan` + `validate_plan`.
2. **`test_swap_then_rate`**: pre-seeded plan → "swap Wed for something lighter" → confirm → "we cooked Mon and loved it" → assert `update_plan` then `record_rating`.
3. **`test_cookidoo_import`**: "show me my Cookidoo collections" → "import recipe r471786" → assert `list_cookidoo_collections` + `fetch_cookidoo_recipe`; new recipe in file.
   *Skipped unless `cookidoo_user`/`cookiday_pass` env vars are set — `@pytest.mark.skipif`.*

### How evals run

`tests/evals/conftest.py`:

- Per-test fixture creates a temp `state/` dir, copies `fixtures/*.json` into it (via monkeypatch of `storage.STATE_DIR` or env var).
- Patches `agents.orchestrator.MODEL` if `EVAL_MODEL` env var is set (so you can run cheaper evals against e.g. Haiku for fast iteration).
- After each test, reads the trace summary, appends a row to `traces/eval_runs.csv`:
  `timestamp, test_name, model, prompt_tok, completion_tok, total_tok, latency_ms, tool_call_names, passed, ceiling, baseline_drift_pct`.
- Hard ceilings (declared in the test) → `pytest` assertion failure.
- Baseline drift is informational: if `total_tokens` > 1.2× the median of the last 10 passing runs of the same test, log a warning row but don't fail.

### Eval fixtures

```json
// tests/evals/fixtures/profile_basic.json
{"household_size": 4, "members": [...], "household_dislikes": ["mushrooms"], ...}

// tests/evals/fixtures/recipes_seed.json
[ {"id": "salmon-teriyaki-bowls", ...}, ... ]
```

Tiny enough to commit; gitignore exception will be needed since `state/` and `traces/` are gitignored but `tests/evals/fixtures/` must be tracked.

---

## 6. Project layout after this sub-project

```
meal-planner-agentic/
  app.py                         # +sidebar token caption
  storage.py
  models.py                      # +Recipe.notes field
  tracing.py                     # NEW
  agents/
    orchestrator.py              # +update/delete_recipe tools, tracing hooks
    recipe_finder.py             # +tracing hooks
    prompts.py                   # +edit/delete guidance
  tools/
    profile.py
    state.py
    recipes.py                   # +update_recipe, +delete_recipe
    cookidoo.py
    validate.py
  docs/
    BRD.md                       # NEW
    PRD.md                       # NEW
    BUILD_SPEC.md                # NEW
    architecture.yaml            # NEW
    superpowers/specs/
      2026-04-15-meal-planner-agentic-design.md      # historical
      2026-05-03-edit-recipes-and-tracing-design.md  # this doc
  state/                         # gitignored
  traces/                        # NEW, gitignored
    summary.jsonl
    full/
    eval_runs.csv
  tests/
    unit/                        # existing tests moved here
      test_validate.py
      test_storage.py
      test_search.py
      test_recipes_crud.py       # NEW
      test_tracing.py            # NEW
    evals/                       # NEW
      conftest.py
      fixtures/
        profile_basic.json
        recipes_seed.json
      test_capabilities.py
      test_workflows.py
  pyproject.toml                 # +pytest markers
  README.md                      # +tracing/eval docs
```

`pyproject.toml` additions:

```toml
[tool.pytest.ini_options]
markers = [
    "eval: real-model evals (cost money, opt-in via -m eval)",
]
```

---

## 7. Risks & open items

- **Eval cost & flakiness.** Real-model evals burn tokens on every run and tool-call sequences vary turn-to-turn. Mitigations: opt-in marker, fresh seeded state per test, ceilings set at baseline×1.2, content assertions are loose (e.g. "calls `update_plan`"), not "exact final text". If a test flakes >1 in 5, weaken the assertion.
- **Trace file growth.** No rotation in v1. Acceptable for personal use; revisit if `full/` exceeds ~100MB.
- **Notes field migration.** Adding `Recipe.notes` to existing `recipes.json`. Pydantic needs a default (`notes: str = ""`) so existing rows load without a migration script.
- **`docs/BUILD_SPEC.md` drift.** Hand-maintained against `architecture.yaml` initially. If it drifts in practice, add a generator script. Not in scope.
- **Cookidoo eval gating.** The Cookidoo workflow eval is skipped unless creds are set, so any environment running this without creds won't fail.
- **LiteLLM `response.usage` portability.** Not all OpenRouter-routed providers reliably populate `usage`. Tracing must handle missing fields gracefully (default to 0/None) and surface "tokens unknown" rather than crashing.

---

## 8. Implementation order (high level — full plan generated by writing-plans skill next)

1. Add `Recipe.notes` field + `update_recipe` / `delete_recipe` tools + unit tests.
2. Wire orchestrator + system prompt for edit/delete; manual smoke.
3. Add `tracing.py` + integrate into `run_turn` and `find_new_recipes` + unit tests.
4. Add sidebar token caption in `app.py`.
5. Move existing tests into `tests/unit/`; add `tests/evals/` scaffold + fixtures + capability tests.
6. Add workflow smoke tests.
7. Write `docs/BRD.md`, `docs/PRD.md`, `docs/architecture.yaml`, `docs/BUILD_SPEC.md`.
8. Run `pytest -m eval` once to record baselines; set ceilings in tests at baseline × 1.2.
