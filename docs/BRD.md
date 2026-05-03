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

---

## Problem framing

### Status quo

Weekly dinner planning without this app:

- 30–45 minutes scrolling cookbooks, Cookidoo, and saved links each Sunday.
- Household dislikes and dietary rules (no mushrooms, ≥1 fish/week) held in memory — violated when tired or rushed.
- No record of what was cooked last week; easy to repeat the same rotation.
- Shopping list rebuilt from scratch every week — no pantry awareness.
- Cookidoo recipes are authenticated-only; no way to search them alongside saved recipes without logging in manually each time.
- Ratings ("that one was great, make it again") captured nowhere — lost after dinner-table conversation.

### Why agent-driven, not a form-based app

- **No onboarding wizard.** Form apps require structured input upfront. This agent learns household context conversationally; the profile grows incrementally through `update_profile` calls.
- **Edits via chat are cheaper than UI clicks.** Swapping one slot requires: type one sentence → agent calls `search_recipes` + `update_plan`. A form-based UI would require: open plan, find slot, open picker, filter, select, save. One sentence is faster.
- **Library and pantry are searchable in chat without UI plumbing.** `search_recipes`, `list_recipes`, `read_state` — the agent does the filtering. No filter widgets to maintain.
- **The 80% case is text in / text out.** A rendered plan table and a chat input are the only UI components that matter at one-household scale; everything else is maintenance surface.
- **Context injection is more flexible than form fields.** The system prompt receives `profile_summary` and `state_summary` per-turn — the agent can reason across all state simultaneously. A form can only surface what the designer anticipated.

### Why this approach beats other planner apps

- **No vendor lock-in.** State is plain JSON in `state/`. Editable by hand, backed up with `cp`, inspectable with any text editor. No account deletion risk.
- **Cookidoo + web search are both first-class.** `fetch_cookidoo_recipe` uses authenticated Cookidoo access; `find_new_recipes` hits the web via the `recipe_finder` subagent on `gemini-2.5-flash:online`. Both land in the same `recipes.json`.
- **Hard household rules enforced by a pure function, not LLM judgement.** `validate_plan` in `tools/validate.py` is a deterministic keyword-match validator — no LLM involved. Rules: ≥1 fish/week, every meal has a vegetable, no household dislikes, no mutual `never_again` recipes. Warnings surface verbatim; the agent cannot self-heal them silently.
- **Token cost stays flat as the library grows.** `list_recipes` and `search_recipes` return compact summaries (`SUMMARY_FIELDS` in `tools/recipes.py`). Full recipe rows are fetched via `get_recipe` only when needed for a specific slot.

---

## Risks & assumptions

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM cost runaway | Low | Medium | Sidebar shows last-turn token cost from `traces/summary.jsonl`; eval harness enforces token ceilings per workflow; orchestrator system prompt explicitly instructs the model to minimise tool calls. |
| Model deprecation (Sonnet 4.5/4.6 sunset) | Medium | Low | Model is a single env var (`ORCHESTRATOR_MODEL` read via `architecture.yaml`; currently `openrouter/anthropic/claude-sonnet-4.5`). Switch is one config line. |
| Cookidoo API churn / TOS change | Medium | Medium | Integration isolated in `tools/cookidoo.py`. Failure is graceful: that tool returns an error; rest of app continues. No hard dependency on Cookidoo for planning — it is one source of many. |
| OpenRouter outage / rate limits | Low | Medium | `agents/recipe_finder.py` has exponential backoff retry loop. Orchestrator returns a graceful "tool loop limit hit" message if the subagent never completes. |
| State file corruption | Very low | High | `storage.py` uses atomic writes (`os.replace`). Manual recovery is possible from `traces/full/<turn_id>.json` which stores verbatim message lists. |
| Drift between `architecture.yaml` / `BUILD_SPEC.md` / actual code | Medium | Low | Convention: update both files on every PR that changes a component or tool. Revisit auto-generation from `architecture.yaml` if drift becomes painful (deferred). |
| Household routine change (dietary needs shift, kids grow up) | High (over years) | Low | `update_profile` is a chat command. Profile update takes one turn; no UI rebuild needed. |
| One-person bus factor | Certain | Deliberate non-goal | Single household; no continuity concern. |

---

## Roadmap

### Done

- **`2026-04-15` — Initial agent** ([spec](superpowers/specs/2026-04-15-meal-planner-agentic-design.md)):
  Chat-driven plan/edit/pantry/ratings + saved recipe library (`recipes.json`) + web search subagent (`recipe_finder`) + Cookidoo import + `validate_plan` hard-rule validator. Streamlit UI with plan table and sidebar.

- **`2026-05-03` — Recipe editing, tracing, evals** ([spec](superpowers/specs/2026-05-03-edit-recipes-and-tracing-design.md)):
  `update_recipe` / `delete_recipe` tools + tiered tracing (`traces/summary.jsonl` + `traces/full/<turn_id>.json`) + `pytest -m eval` real-model harness + `traces/eval_runs.csv` + this docs scaffold (`BRD.md`, `PRD.md`, `BUILD_SPEC.md`, `architecture.yaml`).

### Next sub-project (planned)

Cookidoo timeout & query-complexity fix. Candidate tactics (hypotheses to investigate):

- **Scripted tools instead of free-form query** — replace `get_cookidoo_collection` free-text with a parameterised call that returns a fixed number of results; reduces parse complexity.
- **Reduce inter-agent context sharing** — Cookidoo subagent, if split out, would get only the query and household dislikes — not the full state summary.
- **Shared in-process memory for collection lists** — cache the collection list in the orchestrator process so `list_cookidoo_collections` doesn't re-authenticate on every turn.
- **Split the Cookidoo subagent from the orchestrator's context** — isolate Cookidoo calls into a dedicated subagent (like `recipe_finder`) so a timeout doesn't stall the main chat loop.

### Backlog (unprioritised)

| Item | Notes |
|---|---|
| Cozi integration | Push generated plan to Cozi; add missing pantry items to Cozi shopping list. |
| Recipe edit via UI | Chat-only today. Form-based editor for bulk cleanup. |
| Multi-week plan view | Today: one active week + `plan_history` archive. |
| Day-of-meal granularity | Today: swap whole slots only. |
| Embeddings-backed `search_recipes` | Current search is keyword token-match. Only worth it at ~500+ recipes. |
| Token-use trend chart | Data exists in `traces/summary.jsonl`; no visualisation yet. |
| Per-test pass/fail in `eval_runs.csv` | Current eval harness appends one row per test invocation but uses `request.session.testsfailed` — session-level, not per-test granularity. |
