# meal-planner-agentic

Chat-driven Mon-Fri dinner planner. The Orchestrator agent owns all State writes (`state/profile.json`, `state/recipes.json`, `state/state.json`); a Recipe finder Subagent does web search on explicit user request only.

## Required reading before any work

1. **`CONTEXT.md`** at the repo root. Use the canonical terms (Plan, Slot, Recipe, Source, Hard rule, Subagent, Turn, Snapshot, etc.) as defined there. Do not use the listed `_Avoid_` aliases anywhere, code or comments.
2. **`README.md`** for setup, state files, and test invocation.
3. **`../docs/meal-planner-agentic/`** for project-level docs (BRD, PRD, BUILD_SPEC, architecture.yaml, features plan). Read these before any feature work; they live one level up because they are shared with sibling project docs.
4. **`docs/superpowers/specs/`** for per-sub-project design specs and **`docs/superpowers/plans/`** for implementation plans.

If a change conflicts with `CONTEXT.md` or one of the project docs, surface the conflict explicitly and propose either an updated term or a doc revision. Do not silently diverge.

## Key commands

Run from `C:/Users/migst/personal-kb/05-projects/meal-planner-agentic`. The README uses `.venv/Scripts/pytest.exe` directly rather than `uv run pytest`; prefer that for the existing test commands.

| Command | Purpose |
|---|---|
| `uv venv; uv pip install -e ".[dev]"` | One-time install |
| `streamlit run app.py` | Launch the chat UI at http://localhost:8501 |
| `.venv/Scripts/pytest.exe -v` | Unit tests only (default; fast, free) |
| `.venv/Scripts/pytest.exe -m eval -v` | Opt-in real-model evals (cost tokens, append rows to `traces/eval_runs.csv`) |
| `python scripts/cookidoo_smoke.py` | Manual Cookidoo connectivity check |

## Models

Configured via `.env`. Defaults set in code:

| Env var | Default | Used by |
|---|---|---|
| `ORCHESTRATOR_MODEL` | `openrouter/anthropic/claude-sonnet-4.5` | `agents/orchestrator.py` |
| `RECIPE_FINDER_MODEL` | `openrouter/google/gemini-2.5-flash:online` | `agents/recipe_finder.py` |
| `OPENROUTER_API_KEY` | required | both |

The `:online` suffix on the Recipe finder model routes web search via Exa through OpenRouter; do not strip it without replacing the search mechanism.

## Where things live

- `app.py` -- Streamlit chat UI; renders sidebar with last-Turn cost.
- `agents/orchestrator.py` -- the Orchestrator agent, tool dispatcher, Background job registry, history trimming.
- `agents/recipe_finder.py` -- the Recipe finder Subagent (isolated LLM call, web-enabled).
- `agents/prompts.py` -- system prompts for both agents.
- `tools/profile.py`, `tools/state.py`, `tools/recipes.py`, `tools/cookidoo.py`, `tools/validate.py` -- tool implementations exposed to the Orchestrator via `TOOL_DEFINITIONS`.
- `models.py` -- Pydantic models for Profile, Member, Recipe, Rating, MealPlanSlot, ArchivedPlan, State.
- `storage.py` -- JSON read/write to `state/`.
- `tracing.py` -- Trace writers (`traces/summary.jsonl`, `traces/full/<turn_id>.json`, Subagent attachment).
- `state/` -- the three State files. Delete any to reset that slice. Gitignored.
- `traces/` -- per-Turn logs and eval rows. Gitignored.
- `tests/` -- pytest suite. `eval` marker = real-model tests.

## Sharp edges

- **Orchestrator is the only writer of State.** Do not write to `state/*.json` from app code, tools called outside the dispatcher, or scripts. The `Snapshot` / `undo` invariant depends on it.
- **`update_plan` replaces all 5 Slots wholesale.** There is no per-Slot edit operation. To change Wednesday, the Orchestrator must construct and submit the full 5-Slot list.
- **Hard rules return warnings, not errors.** `validate_plan` produces a list of human-readable strings; an empty list means clean. Do not introduce a "block on validation failure" path; warnings surface to the user as advisory.
- **Tool result truncation: 4000 chars.** `MAX_TOOL_RESULT_CHARS` cuts long tool outputs with " ...(truncated)". Tools returning large JSON should pre-summarise (`list_recipes` returns compact summaries; `get_recipe` returns full detail).
- **History trim: last 20 messages.** `_trim_history` drops older turns and any leading orphan `tool` role. The system prompt re-injects current Profile and State each Turn, so older turns are not load-bearing.
- **Recipe finder is explicit-only.** Per the `find_new_recipes` tool description, the Orchestrator should call it only when the user explicitly asks to find or discover recipes. Do not loosen this; silent web calls break the cost story and the Source provenance.
- **Source label is load-bearing.** A Recipe with `source = "knowledge"` was emitted from training data without a web call; `source = "web"` came from the Recipe finder Subagent and has a `source_url`. Tools must preserve and respect the label.
- **Snapshot covers one Turn.** `undo` only reverts the most recent Turn's State changes. Older Snapshots are not addressable; do not promise multi-step undo without designing it.
- **Tool-loop ceiling: 15 iterations.** `MAX_TOOL_ITERATIONS` caps reasoning; hitting it returns "(tool loop limit hit -- simplify your request)". A turn that hits the ceiling is a smell; investigate before raising.
- **Recipe finder semaphore: concurrency 1.** `_api_semaphore` bounds concurrent Subagent runs to avoid OpenRouter rate-limit bursts. Loosen only with a documented justification.
- **2-second pause between tool iterations.** Hardcoded `time.sleep(2)` after iteration 0. Rate-limit avoidance, not a UX choice.
- **No em-dashes anywhere** (Miguel's repo-wide rule). Use commas, semicolons, colons, parentheses, hyphens, periods.
- **Windows + uv only.** Never invoke bare `python`; always `uv run python` for ad-hoc scripts. PowerShell has no `&&`/`||` chaining.
- **AVG / Avast TLS interception (two-part workaround).** AVG sets `SSLKEYLOGFILE=\\.\avgMonFltPro...` system-wide and MitMs outbound TLS with its own root CA. That breaks Python in two ways:
  1. Honoring the device-path keylog file loads System32's LibreSSL `libcrypto.dll`, which lacks `OPENSSL_Applink` and aborts the process the moment any module imports `ssl` (`import litellm`, `import aiohttp` in 3.13.x, etc).
  2. AVG's root CA lives in Windows' cert store but not in certifi's bundle, so libraries that pin certifi (httpx, litellm) fail with `CERTIFICATE_VERIFY_FAILED` on every outbound call.

  Top-level `conftest.py` and the bootstrap at the top of `app.py` pop the env var **and** call `truststore.inject_into_ssl()` to route Python's `ssl` through the Windows cert store. Both fire only when AV markers are detected (no-op on Linux/Docker). Don't remove either half. If you see `OPENSSL_Uplink ... no OPENSSL_Applink`, check `$env:SSLKEYLOGFILE` first; if you see `CERTIFICATE_VERIFY_FAILED`, confirm the bootstrap ran (`truststore` not installed = no-op).

## Adding a new tool

1. Implement the function in `tools/...`. Pure function returning a JSON-serialisable dict; tools must not write State outside the dispatcher.
2. Add a tool definition to `TOOL_DEFINITIONS` in `agents/orchestrator.py`. Use the OpenAI function-calling shape (`type: function`, `parameters` JSON Schema).
3. Add a dispatch branch in `_dispatch`. Catch exceptions and return them as a JSON `{"error": ...}` so the loop survives.
4. If the tool emits Recipes, set `source` correctly (`cookidoo` | `web` | `manual` | `knowledge`) and persist via `tools/recipes.py`, not by hand-writing JSON.
5. Add unit tests under `tests/`. Tag any test that calls the live model with `@pytest.mark.eval`; default test runs must remain free.
6. Update `CONTEXT.md` if the tool introduces a new domain term. Open an ADR if the change is hard-to-reverse, surprising, or a real trade-off (e.g. relaxing the Orchestrator-as-sole-writer invariant).

## Adding a new Subagent

1. Add a module under `agents/` with its own system prompt in `agents/prompts.py`.
2. Spawn it from a tool dispatcher branch, never from app code. Use `tracing.start_turn` / `tracing.end_turn` and `tracing.attach_subagent(parent_turn_id, ...)` so the Trace tree stays intact.
3. Decide whether it runs inline (blocks the Turn) or as a Background job (`_bg_jobs`); document the choice. Inline is simpler; Background is required when the Subagent run dwarfs a normal Turn's latency.
4. Bound concurrency with a semaphore if the Subagent calls a rate-limited API.
5. Update `CONTEXT.md` to extend the **Subagent** entry with the new instance.
