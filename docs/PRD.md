# Product Requirements Document

> Living document. Each sub-project updates the affected capability sections and appends new ones.

## Capabilities

### 1. Plan Mon–Fri dinners

**User story:** As the cook, I ask the agent to plan next week's dinners and get back a 5-slot table I can immediately use.

**Detailed scenarios:**

```
user: Plan next week's dinners.
agent: [internally uses profile + state summary from system prompt context]
       [calls update_plan with 5 slots; validate_plan runs inline]
agent: Here's the plan:
       | Day | Recipe | Protein | Cook time |
       | Mon | ...    | ...     | ...       |
       ...
       (No validation warnings.)
```

```
user: Plan next week. We have chicken thighs in the freezer.
agent: [no read_state call — pantry is already in the state summary]
       [calls update_plan; validate_plan fires: "No fish this week"]
agent: Planned! One warning: no fish this week — at least 1 fish meal is expected.
       Want me to swap one slot for a fish dish?
```

**Acceptance criteria:**
- Agent produces a 5-slot table (Mon–Fri) in one turn without requiring the user to specify every slot.
- `update_plan` is called once; `validate_plan` runs inline and returns warnings in the same result.
- Validation warnings are surfaced verbatim in the agent response — not paraphrased, not silently corrected.
- Agent does not call `read_profile` or `read_state` if the system prompt context already reflects current state.
- Agent confirms the plan before calling `update_plan` (unless user said "just do it").

**Tools that implement this:**
- `update_plan` — writes the 5-slot plan to `state.json`; runs `validate_plan` inline.
- `read_state` — only called if user changed something mid-turn and stale context is a concern.
- `read_profile` — only called on first run (empty profile triggers onboarding).
- `validate_plan` — pure validator; called automatically inside `update_plan`.

**Edge cases:**
- Profile is empty (first run): orchestrator detects empty profile and opens onboarding chat before planning.
- Fewer than 5 meals requested: agent plans the requested subset and leaves remaining slots empty.
- All high-rated recipes also violate a hard rule: validation warning surfaced; agent asks user to decide.
- Last week's plan is in `plan_history`: agent avoids repeating those recipes (Rule 5 in `validate_plan`).

**Known gaps / deferred:**
- No recurring schedule support (e.g. "always fish on Friday").
- No cross-week optimisation (e.g. batch-cooking awareness).
- No cost or calorie budgeting.

---

### 2. Edit existing plan via chat

**User story:** As the cook, I describe what I want to change in plain text and the plan updates without me touching a UI.

**Detailed scenarios:**

```
user: Swap Wednesday for something lighter.
agent: [calls search_recipes with query "light"]
agent: How about Grilled Lemon Chicken with zucchini (30 min)? Want me to update Wed?
user: Yes.
agent: [calls update_plan with the modified 5-slot list]
agent: Done. Wednesday is now Grilled Lemon Chicken.
```

```
user: Move Thursday's meal to Tuesday and put pasta on Thursday.
agent: [calls update_plan with the swapped slots]
agent: Updated. Tue is now [prev Thu], Thu is now pasta.
```

**Acceptance criteria:**
- Single-slot edits complete in ≤2 turns (suggestion + confirm).
- Agent calls `update_plan` with a full 5-slot diff, not just the changed slot.
- `validate_plan` runs and warnings are surfaced if the edit introduces a violation.
- "Just do it" or "go ahead" bypasses the confirmation step.

**Tools that implement this:**
- `search_recipes` — keyword search against `recipes.json` to find swap candidates.
- `update_plan` — writes the updated plan; runs `validate_plan` inline.
- `read_state` — if agent needs to see the current plan before editing.

**Edge cases:**
- User references a recipe not in the library: agent suggests one from library or asks if they want to search.
- Edit would put the same recipe twice in a week: agent notices and flags it.
- Edit resolves a pre-existing validation warning: agent notes the warning is cleared.

**Known gaps / deferred:**
- Day-of-meal granularity (swap one component, not the whole slot) — deferred.
- Undo for plan edits exists (`undo` tool in orchestrator) but is not prominently surfaced in the UI.

---

### 3. Pantry tracking

**User story:** As the cook, I can tell the agent what's in or out of the pantry so it can factor pantry stock into planning suggestions.

**Detailed scenarios:**

```
user: We're out of rice.
agent: [calls update_pantry({remove: ["rice"]})]
agent: Noted — rice removed from pantry.
```

```
user: I picked up salmon and tinned tomatoes today.
agent: [calls update_pantry({add: ["salmon", "tinned tomatoes"]})]
agent: Added both to pantry.
```

**Acceptance criteria:**
- `update_pantry` accepts `add` and `remove` lists; writes to `state.json`.
- Pantry contents are visible in the Streamlit sidebar (pill display).
- Agent factors pantry contents into planning suggestions via soft preference ("favour pantry-aligned recipes").
- Confirmation before `update_pantry` unless user said "just do it".

**Tools that implement this:**
- `update_pantry` — writes `state.json`; accepts `add` / `remove` lists.
- `read_state` — if agent needs to check current pantry contents mid-turn.

**Edge cases:**
- User removes an item not in the pantry: `update_pantry` handles gracefully (no-op or warning).
- User adds duplicates: deduplicated at the model level or silently ignored.

**Known gaps / deferred:**
- Quantities not tracked (in/out only). "We have half a bag of rice" is not representable.
- No expiry date tracking.
- No automatic pantry deduction after a meal is cooked.

---

### 4. Recipe library

**User story:** As the cook, I can grow and search a personal recipe library that the agent draws on when planning.

**Detailed scenarios:**

```
user: Find me 3 new bacalhau recipes.
agent: [calls find_new_recipes("bacalhau", count=3)]
       [recipe_finder subagent runs web search; returns 3 Recipe objects]
       [appended to recipes.json; duplicates skipped by id]
agent: Found and saved 3 bacalhau recipes:
       - Bacalhau à Brás (Portuguese) — 45 min
       - Bacalhau com Natas — 60 min
       - Bacalhau à Lagareiro — 50 min
```

```
user: What fish recipes do we have?
agent: [calls search_recipes("fish") or list_recipes({main_protein: "fish"})]
agent: 7 fish recipes in the library: [compact table]
```

**Acceptance criteria:**
- `find_new_recipes` spawns `recipe_finder` subagent (Gemini 2.5 Flash :online), appends results to `recipes.json`, skips duplicates by `id`.
- `list_recipes` and `search_recipes` return compact summaries (no `key_ingredients`, no `notes` blobs) — full recipe loaded via `get_recipe` only when needed.
- `search_recipes` ranks by token match count, then `avg_rating` desc, then `times_cooked` desc.
- Per-turn token use stays roughly flat as `recipes.json` grows (summaries, not full rows, in most responses).

**Tools that implement this:**
- `list_recipes` — returns compact summaries; supports exact-match filters on `FILTERABLE_FIELDS`.
- `search_recipes` — keyword token-match across title/cuisine/protein/tags/ingredients.
- `get_recipe` — returns full recipe dict for a given `id`.
- `find_new_recipes` — spawns subagent; writes `recipes.json`.

**Edge cases:**
- Web search returns a recipe matching an existing `id` (same slug): silently skipped by `append_recipes`.
- Library grows to 500+ recipes: keyword search degrades in relevance. Embeddings-backed search is deferred.
- `recipe_finder` subagent times out or returns malformed JSON: orchestrator logs the error; no partial writes to `recipes.json`.

**Known gaps / deferred:**
- No embeddings-backed semantic search. Current is keyword token-match. Deferred until library exceeds ~500 recipes.
- No bulk import (e.g. CSV of recipes).
- No deduplication by title — only by `id` (slug).

---

### 5. Recipe editing & deletion *(added 2026-05-03)*

**User story:** As the cook, I can fix mistakes or remove unwanted recipes from the library via chat, without touching a file.

**Detailed scenarios:**

```
user: The cuisine on salmon teriyaki is wrong — it should be Japanese.
agent: Update salmon-teriyaki: cuisine → "Japanese". Confirm?
user: Yes.
agent: [calls update_recipe("salmon-teriyaki", {cuisine: "Japanese"})]
agent: Done. Salmon Teriyaki cuisine updated to Japanese.
```

```
user: Delete the failed cassoulet.
agent: cassoulet-fail is not in the current meal plan. Delete it?
user: Yes.
agent: [calls delete_recipe("cassoulet-fail")]
agent: Deleted.
```

**Acceptance criteria:**
- `update_recipe` accepts a `recipe_id` and a `fields` dict; merges only the supplied fields; `id` and `added_at` are immutable (`_IMMUTABLE_FIELDS` in `tools/recipes.py`).
- `delete_recipe` returns `True` on success; if the recipe is in the current `meal_plan`, agent warns before deleting.
- Agent confirms before calling either mutation tool unless user said "just do it".
- After edit, agent returns the updated summary fields.

**Tools that implement this:**
- `update_recipe` — merge-updates mutable fields; writes `recipes.json`.
- `delete_recipe` — removes by `id`; writes `recipes.json`.
- `search_recipes` / `list_recipes` — used to find the `recipe_id` when user refers by title.

**Edge cases:**
- User provides a title that matches multiple recipes: agent lists candidates and asks for clarification.
- User attempts to change the `id` field: silently dropped (`_IMMUTABLE_FIELDS` guard).
- Recipe being deleted is in the current plan: agent surfaces a warning before proceeding.
- `recipe_id` not found: `update_recipe` returns `None`; `delete_recipe` returns `False`; agent reports not found.

**Known gaps / deferred:**
- No UI-based recipe editor (chat-only today). Deferred.
- No bulk edit / bulk delete. One recipe per command.
- No soft-delete / archive — deletion is permanent.

---

### 6. Hard-rule validation

**User story:** As the cook, household dietary rules are enforced automatically — the agent cannot silently produce a plan that violates them.

**Detailed scenarios:**

```
user: Plan next week.
agent: [update_plan returns: warnings = ["No fish this week — at least 1 fish meal is expected."]]
agent: Plan saved. Warning: No fish this week — at least 1 fish meal is expected.
       Want me to swap one slot for a fish dish?
```

```
user: Add mushroom risotto to Wednesday.
agent: [update_plan returns: warnings = ["Wednesday (Mushroom Risotto) violates household dislike: mushroom"]]
agent: Warning: Mushroom Risotto violates household dislike: mushroom. Proceed anyway?
```

**Acceptance criteria:**
- `validate_plan` is a pure Python function — no LLM call, no side effects.
- Four rules enforced: (1) ≥1 fish/seafood meal per week, (2) every slot has a vegetable, (3) no household dislike appears in `key_ingredients`, (4) no recipe both adults rated `never_again`.
- Rule 5: no recipe from last week's plan (checked against `plan_history[-1]` if present).
- Warnings are returned in the `update_plan` result and surfaced verbatim. Agent does not auto-fix.
- Fish and vegetable detection uses keyword lists (`FISH_KEYWORDS`, `PRODUCE_KEYWORDS` in `tools/validate.py`); substring match on `key_ingredients`.

**Tools that implement this:**
- `validate_plan` — pure validator; called automatically inside `update_plan`. Can also be called standalone.
- `update_plan` — wraps `validate_plan`; includes `warnings` in its return value.

**Edge cases:**
- Plan has fewer than 5 slots: Rule 1 (fish) still fires if no slot has a fish ingredient.
- Both adults have zero ratings: Rule 4 is vacuously satisfied (no `never_again` entries).
- `plan_history` is empty (first week): Rule 5 is skipped.
- Ingredient spelling variation (e.g. "sea bass" vs "seabass"): both are in `FISH_KEYWORDS`.

**Known gaps / deferred:**
- Keyword match is substring-based — a recipe titled "fisherman's stew" with no fish in `key_ingredients` would not satisfy Rule 1.
- No "soft rule" enforcement — preferences (avoid recent repeats, favour pantry) are in the system prompt only.
- No override mechanism — if user wants to schedule a `never_again` recipe anyway, they must edit the rating first.

---

### 7. Web search subagent

**User story:** As the cook, I can ask the agent to discover new recipes from the web and have them saved to my library automatically.

**Detailed scenarios:**

```
user: Find me 3 quick Thai recipes under 30 minutes.
agent: [calls find_new_recipes("Thai under 30 minutes", count=3)]
       [orchestrator spawns recipe_finder; assigns job_id; returns immediately]
agent: Searching... I'll let you know when results are in.
       [background: recipe_finder runs, calls web_search via OpenRouter :online suffix]
       [on completion: 3 Recipe objects appended to recipes.json]
agent: Found 3 Thai recipes (all under 30 min) and saved them:
       - Pad Thai (Thai) — 25 min
       - Green Curry (Thai) — 20 min
       - Thai Basil Stir Fry (Thai) — 15 min
```

**Acceptance criteria:**
- `find_new_recipes` spawns `recipe_finder` as an isolated subagent (separate LiteLLM context).
- `recipe_finder` uses `gemini-2.5-flash:online` — web search is routed via OpenRouter `:online` model suffix.
- Results filtered against household dislikes before returning to orchestrator.
- Newly added recipes appended to `recipes.json`; duplicates skipped by `id`.
- Subagent trace attached to parent turn via `tracing.attach_subagent`.
- Long-running searches can be backgrounded; `check_search_status` polls completion.

**Tools that implement this:**
- `find_new_recipes` — spawns `recipe_finder`; appends results; returns compact summaries of added recipes.
- `check_search_status` — polls background job registry for a given `job_id`.

**Edge cases:**
- Query contains `site:cookidoo.com.au`: `recipe_finder` stays on that domain even if results are paywalled (system prompt exception in `RECIPE_FINDER_SYSTEM_PROMPT`).
- Subagent returns malformed JSON: orchestrator logs error; no partial writes.
- All results violate household dislikes: subagent returns empty list; orchestrator reports "no suitable recipes found".
- OpenRouter rate limit hit: exponential backoff in `recipe_finder`; orchestrator surfaces error after max retries.

**Known gaps / deferred:**
- No deduplication by title — only by `id` (slug). Two recipes with different slugs but identical names can coexist.
- No user review step before saving — results go straight to `recipes.json`. Planned: "here's what I found, save all?" flow.
- Source quality is heuristic (preferred sites listed in `RECIPE_FINDER_SYSTEM_PROMPT`); no verification.

---

### 8. Cookidoo integration

**User story:** As the cook, I can browse my Cookidoo library and import individual recipes directly into my recipe library via chat.

**Detailed scenarios:**

```
user: What's in my Cookidoo library?
agent: [calls list_cookidoo_collections()]
agent: You have 4 collections: Weeknight Dinners, Asian Favourites, Baking, Soups & Stews.
```

```
user: Import Cookidoo recipe r471786.
agent: Fetching r471786 from Cookidoo...
       [calls fetch_cookidoo_recipe("r471786")]
agent: Saved: Salmon with Lemon Butter (Seafood, 25 min). Added to library.
```

```
user: Show me recipes in my Asian Favourites collection.
agent: [calls get_cookidoo_collection("asian-favourites-col-id")]
agent: 12 recipes in Asian Favourites: [compact table]
```

**Acceptance criteria:**
- `fetch_cookidoo_recipe` authenticates via `cookidoo_user` / `cookidoo_pass` env vars, fetches structured recipe data, and appends to `recipes.json`.
- `list_cookidoo_collections` and `get_cookidoo_collection` return collection metadata without writing state.
- Auth happens per-call (no persistent session today).
- Cookidoo failure is graceful: tool returns an error message; rest of app continues unaffected.

**Tools that implement this:**
- `list_cookidoo_collections` — lists authenticated Cookidoo collections.
- `get_cookidoo_collection` — returns recipes in a given collection.
- `fetch_cookidoo_recipe` — fetches recipe by id; writes `recipes.json`.

**Edge cases:**
- Invalid recipe id: Cookidoo API returns error; `fetch_cookidoo_recipe` surfaces it; no write to `recipes.json`.
- Recipe already in library: `append_recipes` skips the duplicate by `id`.
- Cookidoo credentials missing from env: tool returns an auth error immediately.
- Large collections: `get_cookidoo_collection` may time out on collections with many recipes (known issue; next sub-project).

**Known gaps / deferred:**
- Per-call login — no connection pooling. Each Cookidoo tool call re-authenticates. Planned fix: next sub-project.
- Queries on large collections time out. Known issue; planned fix: scripted tool parameters, reduced context sharing.
- No Cookidoo grocery-list push (planned future sub-project).

---

### 9. Tracing & evals *(added 2026-05-03)*

**User story:** As the maintainer, I can see what each chat turn cost (tokens, latency) and run a regression suite against the real model without polluting normal test runs.

**Detailed scenarios:**

```
[after a planning turn]
Streamlit sidebar: "Last turn: 1,240 tok / 3.2s"
```

```
$ pytest -m eval -v
tests/test_evals.py::test_plan_turn PASSED
tests/test_evals.py::test_recipe_search PASSED
[appends rows to traces/eval_runs.csv]
```

**Acceptance criteria:**
- Every chat turn writes one line to `traces/summary.jsonl`: `turn_id`, `timestamp`, `model`, `n_llm_calls`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `latency_ms`, `tool_calls[]`, `subagent_calls[]`.
- Full message list written to `traces/full/<turn_id>.json` for replay/debug.
- Trace writes are best-effort: any exception inside `tracing.py` is swallowed; the chat loop never fails due to tracing.
- Streamlit sidebar reads `last_turn_summary()` after each turn and displays token + latency.
- `pytest -m eval` runs real-model tests; unmarked tests are all-synthetic (no LLM calls).
- Each eval run appends a row to `traces/eval_runs.csv`.
- Subagent traces are nested under the parent turn via `tracing.attach_subagent`.

**Tools that implement this:**
- `tracing.start_turn` — creates an in-memory turn record; returns `turn_id`.
- `tracing.record_completion` — accumulates token counts and latency per LLM call.
- `tracing.record_tool_call` — appends tool call digest to the turn record.
- `tracing.end_turn` — flushes to `summary.jsonl` and `full/<turn_id>.json`; removes in-memory record.
- `tracing.attach_subagent` — nests subagent summary under parent turn.
- `tracing.last_turn_summary` — reads last line of `summary.jsonl` for sidebar display.

**Edge cases:**
- `traces/` directory does not exist: `_ensure_dirs()` creates it on first `end_turn` call.
- Concurrent turns (if UI ever supports parallel requests): protected by `threading.Lock` in `tracing.py`.
- `turn_id` not found in `_turns` on `end_turn` (e.g. process restart mid-turn): no-op, no error.
- `summary.jsonl` grows unboundedly: no rotation implemented today.

**Known gaps / deferred:**
- No trace file rotation or size management. Deferred until size is a problem.
- `eval_runs.csv` records per-test invocation but session-level pass/fail count (`request.session.testsfailed`), not per-test pass/fail granularity.
- No token-use trend chart (data exists in `summary.jsonl`; visualisation deferred).

---

## Personas / canonical scenarios

### 1. Sunday-evening planning session

```
user: Plan next week's dinners.
agent: [uses profile + state summary from system prompt; calls update_plan once]
agent: Here's the plan:
       | Mon | Baked Salmon with roasted veg | Fish | 35 min |
       | Tue | Chicken Tikka Masala          | ...  | 45 min |
       | ... | ...                           | ...  | ...    |
       No validation warnings.
user: Can you swap Thursday for something Portuguese?
agent: [calls search_recipes("Portuguese")]
agent: How about Bacalhau à Brás (45 min)? Confirm?
user: Yes.
agent: [calls update_plan with Thu updated]
agent: Done. Thursday is now Bacalhau à Brás.
```

Total user effort: ~3 sentences. Under 60 seconds.

---

### 2. Mid-week swap

```
user: Kids are sick, swap Wednesday for something simple.
agent: [calls search_recipes("simple easy")]
agent: Pasta al Pomodoro (20 min)? It's in the library. Confirm?
user: Perfect, go ahead.
agent: [calls update_plan]
agent: Wednesday updated to Pasta al Pomodoro.
```

2 turns. Under 30 seconds.

---

### 3. Post-dinner rating

```
user: Rate Monday's salmon 5 stars — make it again soon.
agent: [calls record_rating({recipe_title: "Baked Salmon", rater: "Miguel", rating: "again_soon"})]
agent: Rated. Baked Salmon marked as "again soon" for Miguel.
```

1 turn.

---

### 4. Discovering a new dish

```
user: Find me 3 quick Thai recipes.
agent: [calls find_new_recipes("Thai", count=3); spawns recipe_finder subagent]
agent: Searching... (may take ~30s)
       [subagent completes; 3 recipes appended to recipes.json]
agent: Found 3 Thai recipes:
       - Pad Thai (25 min)
       - Green Curry (20 min)
       - Thai Basil Stir Fry (15 min)
       All saved to library.
user: Add the Green Curry to next Thursday.
agent: [calls update_plan with Thu = Green Curry]
agent: Done.
```

3 turns.

---

### 5. Importing from Cookidoo

```
user: Import Cookidoo recipe r471786.
agent: [calls fetch_cookidoo_recipe("r471786")]
agent: Saved: Salmon with Lemon Butter (Seafood, 25 min). Added to your library.
```

1 turn.

---

### 6. Cleaning up the library

```
user: The cuisine on salmon teriyaki is wrong — change it to Japanese.
agent: Update salmon-teriyaki: cuisine → "Japanese". Confirm?
user: Yes.
agent: [calls update_recipe("salmon-teriyaki", {cuisine: "Japanese"})]
agent: Done. Cuisine updated to Japanese.

user: And delete the failed cassoulet.
agent: cassoulet-fail is not in this week's plan. Delete it permanently?
user: Yes.
agent: [calls delete_recipe("cassoulet-fail")]
agent: Deleted.
```

4 turns total for two edits.

---

## Known gaps / deferred (cross-capability)

- **Multi-week planning** — one active week at a time. Previous weeks archived to `plan_history` in `state.json` but no multi-week view.
- **Day-of-meal granularity** — plan slots are whole meals. Swapping one component (e.g. the side dish) requires replacing the full slot.
- **Quantities in pantry** — binary in/out only. "Half a bag of rice" is not representable.
- **Recipe-edit UI** — chat-only today. No form-based editor for bulk metadata cleanup.
- **Cozi integration** — push generated meal plan to Cozi; add missing pantry items to Cozi shopping list. Planned future sub-project.
- **Cookidoo query-complexity / timeout** — large Cookidoo collections cause per-call login and query timeouts. In-progress next sub-project.
