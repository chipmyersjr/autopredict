# Design 3, part 1 — Game info ingress frontend

Area status: `not_started`

## Objective and governing design

Add the accepted Games-page Refresh flow under [design/3_game_info_ingress.html](../../../design/3_game_info_ingress.html), especially sections 2–7, and [design/1_mvp.html](../../../design/1_mvp.html) sections 4 and 8. Preserve [design/4_shared_strategies.html](../../../design/4_shared_strategies.html) shared-strategy behavior.

Planning status: ready, revalidated October 3, 2026. Area status tracks runtime delivery: FE-01 and FE-02 remain not_started. Earlier logs are history; accepted defaults no longer await review.

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

### Settled implementation details

- Extend `frontend/src/api/games.ts` and `GamesPage.tsx`. Add an explicit current-window option for this page while preserving the unfiltered helper for existing callers. Preserve API ordering and existing strategy/dry-run interactions.
- POST `/api/games/refresh` with no selected week or automatic retries. Parse the section-7 envelope on handled non-2xx responses as well as HTTP 200; `success` determines outcome. Display the backend safe `message` in one accessible dismissible dialog, restoring focus to Refresh. Transport errors and malformed/missing envelopes use a generic failure message.
- Disable Refresh and guard duplicate dispatch while pending; release request state in every completion/error path. Browser cancellation does not clear backend ownership. When `data_changed` is true, reload stored data once, including after partial failure. A reload failure uses the existing games-loading error, not a second refresh popup.
- Empty current-week data prompts the user to Refresh. Empty-week success includes “No FBS games this week.” Backend messages own remaining counts, Sunday reservation, and retry/reset wording; do not calculate quotas or automatically retry in the browser.
- Completed games display supplied scores. Kickoff-reached labels remain distinguishable from provider-confirmed status. Real current-week games must not carry the existing blanket demo-data label; retain demo labels wherever fixtures are displayed. Describe odds as saved observations.

- [ ] FE-01 — Add Refresh button and popup
  - Status: not_started
  - Scope: One button on the Games page, disabled during its request; POST refresh; popup success with remaining refreshes or failure with safe backend reason. Use GET window=current to load/reload stored games, including after partial success when data_changed is true.
  - Dependencies: Completed `1_1_mvp_vertical_slice_1` Games view; ingress BE-11 endpoint/current-window contract. GET/POST CORS already exists.
  - Acceptance criteria: Opening page does not call external providers; click calls refresh once; successful result shows “Refresh successful. X refreshes remaining this week”; partial/failure messages explain results and limits; transport failure shows generic failure; button recovers in every path. Empty-state prompt, empty-week success, completed scores, kickoff labels, and accurate demo labeling work. Existing strategy/dry-run controls remain functional. No status panel/extra refresh controls.
  - Validation: Frontend interaction tests for success, partial/blocked/error, double click prevention, re-enable, reload-after-changes including partial HTTP 200, handled 429/409/503/422 envelopes, malformed responses, empty week, popup accessibility/focus, scores/labels, existing controls, and no refresh on mount; build/type checks.
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

## Frontend completion criteria

FE-01 and FE-02 are complete and validated against BE-11. The page reads stored current-week data without provider work, performs one explicit refresh per click, reports full/empty/partial/blocked/error outcomes accurately, and reloads committed changes. Both areas must satisfy their completion criteria before the epic is complete.

### 2026-10-03 — Plan revalidation

- Completed task IDs: None; FE-01 and FE-02 remain not_started. The implementation plan is ready.
- Validation: Compared ingress sections 2–7 with current GamesPage/api helper and completed slice-1 plans. Confirmed the existing Games view reads unfiltered stored data and has no provider Refresh control. Added explicit envelope, empty-state, scores, labeling, accessibility, and existing-controls criteria.
- Affected files: Both ingress plans only. Runtime tests were not run for this document review.
- Blockers: No planning blockers. Runtime integration awaits BE-11; FE-02 also requires BE-12 evidence.
- Next: FE-01 after BE-11, then FE-02. Historical Games-view dependency is satisfied.
