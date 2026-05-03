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
