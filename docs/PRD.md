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
