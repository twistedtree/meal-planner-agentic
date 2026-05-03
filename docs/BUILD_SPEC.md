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
