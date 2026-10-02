# Design 3, part 1 — Game ingress strategy proposal frontend

Area status: `not_started`

## Objective and governing design

Support exploration under `design/1_mvp.html` sections 4 and 8. CHIP requested a simple frontend implementation plan: one Refresh button with a success/failure popup. Implementation is not performed in this planning turn. Governing ingress design: ../../../design/3_game_info_ingress.html, especially sections 3, 4, and 7.

## Tasks

Current design revision: the Games page will have one Refresh button and one success/failure popup with remaining refreshes and an informative failure reason. No UI code is implemented in this planning task. Backend and frontend implementation tasks are defined below.

Earlier research loops had no applicable frontend implementation tasks; current FE-01 and FE-02 are below.

## Loop log

### 2026-09-30

- Completed tasks: None; not applicable.
- Validation: Reviewed existing frontend handoff; no API contracts or UI code changed.
- Blockers: None for this area.
- Next: Plan UI work after ingress choices and metadata contract are adopted.

### 2026-09-30 — On-demand refresh design handoff

- Completed tasks: None; document-only loop, frontend implementation not applicable.
- Validation: Reviewed updated design requirements for Refresh, Monday–Sunday range, separate game/odds timestamps, saved quotes, Sunday reservation, and provider-limit messages.
- Blockers: Implementation is not requested; proposed defaults remain for review.
- Next: Expand frontend tasks alongside backend API contracts when implementation is authorized.

## Current implementation plan (supersedes earlier frontend handoff suggestions)

No quota panel, separate status endpoint, additional controls, or detailed status display. Preserve earlier loop log as history; use current ingress section 7 for the final UI contract.

- [ ] FE-01 — Add Refresh button and popup
  - Status: not_started
  - Scope: One button on the Games page, disabled during its request; POST refresh; popup success with remaining refreshes or failure with safe backend reason. Use GET window=current to load/reload stored games, including after partial success when data_changed is true.
  - Dependencies: Epic 1 frontend Games view; ingress BE-11 API contract and CORS.
  - Acceptance criteria: Opening page does not call external providers; click calls refresh once; successful result shows “Refresh successful. X refreshes remaining this week”; partial/failure messages explain results and limits; transport failure shows generic failure; button recovers in every path. No status panel/extra controls.
  - Validation: Frontend interaction tests for success, partial/blocked/error, double click prevention, re-enable, reload-after-changes, and no refresh on mount; build/type checks.
  - Completion notes: Pending.

- [ ] FE-02 — Validate minimal refresh flow
  - Status: not_started
  - Scope: Browser smoke test using backend full-success, partial-failure, weekly/Sunday/cooldown/provider quota outcomes and current-week stored games.
  - Dependencies: FE-01; BE-12 backend evidence.
  - Acceptance criteria: Popup text/counts match backend; completed Sunday games remain visible; no status dashboard or provider credentials; whole click-to-stored-data path works.
  - Validation: UI build and browser interaction evidence with controlled backend data; record limits and unperformed live checks.
  - Completion notes: Pending.

### 2026-09-30 — Minimal frontend plan accepted direction

- Completed tasks: None; implementation not started.
- Validation: Matched button/popup behavior to ingress response fields and BE-11; no application code changed.
- Blockers: Requires epic 1 Games view and ingress backend endpoint before runtime integration.
- Next: FE-01 after dependencies; keep UI at CHIP’s requested simple scope.

### 2026-09-30 — Progress directory numbering

- Adopted design-number/part-number naming; moved this existing plan without changing task IDs, statuses, or completed work.
- Validation: Sibling plans and governing design links resolve after rename.
- Next: Continue the existing task sequence.
