# Design 3, part 1 — Game info ingress frontend

Area status: `complete`

## Objective and governing design

Add the accepted Games-page Refresh flow under [design/3_game_info_ingress.html](../../../design/3_game_info_ingress.html), especially sections 2–7, and [design/1_mvp.html](../../../design/1_mvp.html) sections 4 and 8. Preserve [design/4_shared_strategies.html](../../../design/4_shared_strategies.html) shared-strategy behavior.

Planning status: ready. Current execution status and evidence are recorded in the task checklist and latest loop entries.

## Tasks

Current design revision: the Games page will have one Refresh button and one success/failure popup with remaining refreshes and an informative failure reason. No UI code is implemented in this planning task. Backend and frontend implementation tasks are defined below.

Earlier research loops had no applicable frontend implementation tasks; current FE-01, FE-03, and FE-02 are below in execution order.

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

- [x] FE-01 — Add Refresh button and popup
  - Status: complete
  - Scope: One button on the Games page, disabled during its request; POST refresh; popup success with remaining refreshes or failure with safe backend reason. Use GET window=current to load/reload stored games, including after partial success when data_changed is true.
  - Dependencies: Completed `1_1_mvp_vertical_slice_1` Games view; ingress BE-11 endpoint/current-window contract. GET/POST CORS already exists.
  - Acceptance criteria: Opening page does not call external providers; click calls refresh once; successful result shows “Refresh successful. X refreshes remaining this week”; partial/failure messages explain results and limits; transport failure shows generic failure; button recovers in every path. Empty-state prompt, empty-week success, completed scores, kickoff labels, and accurate demo labeling work. Existing strategy/dry-run controls remain functional. No status panel/extra refresh controls.
  - Validation: Frontend interaction tests for success, partial/blocked/error, double click prevention, re-enable, reload-after-changes including partial HTTP 200, handled 429/409/503/422 envelopes, malformed responses, empty week, popup accessibility/focus, scores/labels, existing controls, and no refresh on mount; build/type checks.
  - Completion notes: Fixed popup focus containment for Tab and Shift+Tab; expanded controlled browser tests for reopening, dismissal, and focus restoration. Whitespace check passed. Build/browser checks await the runner because Docker access is denied and Node is unavailable. No Git or progress operations performed. Independent checks: Whitespace passed; Prepare sandbox development settings passed; Build frontend dependencies passed; Frontend type/build checks and Chromium browser tests passed. Files: frontend/src/api/games.ts, frontend/src/pages/GamesPage.tsx, frontend/src/styles.css, frontend/tests/games.spec.ts, frontend/tests/refresh.spec.ts, frontend/tests/runs.spec.ts, frontend/tests/strategies.spec.ts, progress/3_1_game_info_ingress/front_end/plan.md, ralph/ingress-frontend.progress.json. Logs: .git/ralph/9754ef8d39f00e2a/FE-01-002.*. Browser automation uses controlled API responses and no real provider credentials. Live-provider browser verification is separate and must not be claimed as passed without evidence.

- [x] FE-03 — Fix imported spread eligibility and team labels
  - Status: complete
  - Scope: Update `frontend/src/pages/GamesPage.tsx` to accept either a complete `home`/`away` pair or a complete pair of the game's team names, matching backend eligibility. Resolve `home` and `away` to the corresponding game team names wherever spread sides appear on the Games page, including strategy preview. Keep API IDs and stored side values unchanged. Governing requirements: ingress design sections 5–6 and existing MVP strategy/dry-run behavior.
  - Dependencies: Existing Games view and ingress BE-09 imported paired spreads; may be implemented independently of FE-01. Complete before FE-02.
  - Acceptance criteria: An upcoming scheduled game with an active market and valid active `home`/`away` selections is selectable and can participate in strategy preview and dry-run creation. Spread labels show team names rather than raw role tokens. Existing team-named demo selections still work. Unknown, duplicate, mixed-format, incomplete, inactive, or invalid-price/line pairs remain unavailable; kickoff and game-status guards remain enforced.
  - Validation: Frontend interaction tests using imported-role and existing team-name fixtures, including selection, preview, and dry-run submission; negative eligibility cases and kickoff boundaries; build/type checks. Manually verify an imported upcoming matchup displays both team names and is selectable when its pair is valid.
  - Completion notes: Implemented complete role/team-name pair eligibility and team labels in spread cards and previews. Added controlled Playwright coverage for selection, preview, dry-run submission, invalid pairs, and kickoff guards. Whitespace checks passed. Build/browser execution awaits the runner: Node is unavailable and Docker access is denied. No protected files or Git state modified. Independent checks: Whitespace passed; Prepare sandbox development settings passed; Build frontend dependencies passed; Frontend type/build checks and Chromium browser tests passed. Files: frontend/src/pages/GamesPage.tsx, frontend/tests/imported-spreads.spec.ts, progress/3_1_game_info_ingress/front_end/plan.md, ralph/ingress-frontend.progress.json. Logs: .git/ralph/9754ef8d39f00e2a/FE-03-003.*. Browser automation uses controlled API responses and no real provider credentials. Live-provider browser verification is separate and must not be claimed as passed without evidence.

- [x] FE-02 — Validate minimal refresh flow
  - Status: complete
  - Scope: Browser smoke test using backend full-success, partial-failure, weekly/Sunday/cooldown/provider quota outcomes and current-week stored games.
  - Dependencies: FE-01; FE-03; BE-12 backend evidence.
  - Acceptance criteria: Popup text/counts match backend; completed Sunday games remain visible; no status dashboard or provider credentials; whole click-to-stored-data path works.
  - Validation: UI build and browser interaction evidence with controlled backend data; record limits and unperformed live checks.
  - Completion notes: Fixed controlled API routing to exclude Vite source modules while preserving strict backend request checks. Whitespace validation passed. Browser/build execution was attempted but Docker socket access is denied and Node is unavailable; runner verification is required. No live-provider checks performed. No protected files or Git state changed. Independent checks: Whitespace passed; Prepare sandbox development settings passed; Build frontend dependencies passed; Frontend type/build checks and Chromium browser tests passed. Files: frontend/tests/imported-spreads.spec.ts, frontend/tests/refresh.spec.ts, progress/3_1_game_info_ingress/front_end/plan.md, ralph/ingress-frontend.progress.json. Logs: .git/ralph/9754ef8d39f00e2a/FE-02-005.*. Browser automation uses controlled API responses and no real provider credentials. Live-provider browser verification is separate and must not be claimed as passed without evidence.

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

FE-01, FE-02, and FE-03 are complete and validated against BE-11. The page reads stored current-week data without provider work, performs one explicit refresh per click, reports full/empty/partial/blocked/error outcomes accurately, and reloads committed changes. Imported paired spreads show team names and remain selectable for eligible upcoming games. Both areas must satisfy their completion criteria before the epic is complete.

### 2026-10-03 — Plan revalidation

- Completed task IDs: None; FE-01 and FE-02 remain not_started. The implementation plan is ready.
- Validation: Compared ingress sections 2–7 with current GamesPage/api helper and completed slice-1 plans. Confirmed the existing Games view reads unfiltered stored data and has no provider Refresh control. Added explicit envelope, empty-state, scores, labeling, accessibility, and existing-controls criteria.
- Affected files: Both ingress plans only. Runtime tests were not run for this document review.
- Blockers: No planning blockers. Runtime integration awaits BE-11; FE-02 also requires BE-12 evidence.
- Next: FE-01 after BE-11, then FE-02. Historical Games-view dependency is satisfied.

### 2026-11-14 — Imported spread UI follow-up

- Completed task IDs: None; added FE-03 at CHIP's request. No implementation statuses changed.
- Validation: Compared Games-page eligibility/rendering with imported `home`/`away` selections, backend support for both complete side formats, and ingress design sections 5–6. Document-only update; runtime tests not run.
- Blockers: None for planning this fix.
- Next: Implement FE-03 before the FE-02 browser validation; retain FE-01 Refresh-flow scope.

### 2026-11-14 21:41 UTC — FE-01 Ralph execution

- Completed tasks: FE-01.
- Validation: Whitespace passed; Prepare sandbox development settings passed; Build frontend dependencies passed; Frontend type/build checks and Chromium browser tests passed.
- Completion notes: Fixed popup focus containment for Tab and Shift+Tab; expanded controlled browser tests for reopening, dismissal, and focus restoration. Whitespace check passed. Build/browser checks await the runner because Docker access is denied and Node is unavailable. No Git or progress operations performed.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.

### 2026-11-14 21:43 UTC — FE-03 Ralph execution

- Completed tasks: FE-03.
- Validation: Whitespace passed; Prepare sandbox development settings passed; Build frontend dependencies passed; Frontend type/build checks and Chromium browser tests passed.
- Completion notes: Implemented complete role/team-name pair eligibility and team labels in spread cards and previews. Added controlled Playwright coverage for selection, preview, dry-run submission, invalid pairs, and kickoff guards. Whitespace checks passed. Build/browser execution awaits the runner: Node is unavailable and Docker access is denied. No protected files or Git state modified.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.

### 2026-11-14 21:48 UTC — FE-02 Ralph execution

- Completed tasks: FE-02.
- Validation: Whitespace passed; Prepare sandbox development settings passed; Build frontend dependencies passed; Frontend type/build checks and Chromium browser tests passed.
- Completion notes: Fixed controlled API routing to exclude Vite source modules while preserving strict backend request checks. Whitespace validation passed. Browser/build execution was attempted but Docker socket access is denied and Node is unavailable; runner verification is required. No live-provider checks performed. No protected files or Git state changed.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.
