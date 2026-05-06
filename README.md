# Meal Planner (Agentic)

Chat-driven weekly dinner planner. Talk to an agent; it maintains your meal plan, pantry, and recipe library as JSON files.

See [design spec](docs/superpowers/specs/2026-04-15-meal-planner-agentic-design.md).

Project docs (BRD / PRD / BUILD_SPEC / architecture.yaml / features plan) live at
`../docs/meal-planner-agentic/` (separated from the app tree so they sit alongside
docs for other projects in `05-projects/docs/`).

## Setup

```bash
uv venv
uv pip install -e ".[dev]"
cp .env.example .env   # fill OPENROUTER_API_KEY (and optionally override model strings)
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
.venv/Scripts/pytest.exe -v          # unit tests only (default; fast, free)
.venv/Scripts/pytest.exe -m eval -v  # opt-in real-model evals (cost tokens)
```

Unit tests cover: validator rules, storage round-trips, search ranking, model
serialization, recipe CRUD, tracing.

Evals replay scripted user turns against the live model and assert tool-call
shape + token ceilings. Each run appends a row to `traces/eval_runs.csv`.

## Tracing

Every chat turn writes:

- `traces/summary.jsonl` — one JSON line per turn: `{turn_id, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, tool_calls}`.
- `traces/full/<turn_id>.json` — full message list for replay / debugging.

Sidebar shows the last turn's cost. `traces/` is gitignored.

## Project docs

Top-level project docs sit one level up at `../docs/meal-planner-agentic/`:

- `../docs/meal-planner-agentic/BRD.md` — business requirements + roadmap (Done, in-progress, Tier-1 planned, Tier-2 deferred, killed)
- `../docs/meal-planner-agentic/PRD.md` — product capabilities (1–9 current; 10–14 planned)
- `../docs/meal-planner-agentic/BUILD_SPEC.md` — current implementation + planned components/tools
- `../docs/meal-planner-agentic/architecture.yaml` — machine-readable architecture (current + planned)
- `../docs/meal-planner-agentic/meal-planner-plan.md` — long-form features plan (Tier 1/2/3 vision)

Sub-project specs and plans live with the app:

- `docs/superpowers/specs/` — per-sub-project design specs
- `docs/superpowers/plans/` — per-sub-project implementation plans
