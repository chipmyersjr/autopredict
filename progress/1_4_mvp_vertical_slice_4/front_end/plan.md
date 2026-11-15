# Design 1, part 4 — Settlement & P&L frontend

Area status: `in_progress`

Planning status: ready. Current execution status and evidence are recorded in the task checklist and latest loop entries.

## Objective and governing design

Make the complete Games → Random Strategy → saved theoretical Bets → settlement → P&L loop visible, including partial results, final Run accounting and a small dashboard.

- [MVP](../../../design/1_mvp.html), sections 5–6, 8–9 (slice 4), and 11.
- [Canonical ERD](../../../design/2_mvp_erd.png), Run metrics and Bet outcome fields.
- [Ingress](../../../design/3_game_info_ingress.html), sections 2, 6–7: explicit final scores, retained history, separate Games Refresh and immutable execution snapshots.
- [Shared strategies](../../../design/4_shared_strategies.html), shared Strategies and User-owned Runs.
- [Completed slice 3 frontend](../../1_3_mvp_vertical_slice_3/front_end/plan.md).
- [Separate ingress frontend](../../3_1_game_info_ingress/front_end/plan.md).
- [Sibling backend plan](../backend/plan.md), the settled shared API/accounting contract and fixture oracle.

## Current implementation and scope

Games creation/preview, hash navigation, Run history/detail, immutable Bet snapshots and nullable outcome rendering exist. Extend those views, add a Run settlement action and #/dashboard. Keep existing Games and Runs links and direct routes working; add Dashboard navigation without changing the existing default Games route. A dedicated Bet history page and strategy management expansion are unnecessary for this bounded slice: Run detail retains Bet history and Dashboard links recent outcomes to Runs.

The server owns finality, spread resolution, rounding, accounting and ownership. No client outcome calculation or result editing, direct provider requests, polling, automatic settlement on page load, or score simulation controls in the production UI. The existing Games Refresh remains the separate ingress flow. Provider absence does not prevent browser acceptance with controlled results in a disposable database.

## Settled UI and API contract

Use the sibling backend contract directly: POST /api/runs/{id}/settle without a body, extended Run/Bet reads and GET /api/dashboard. Keep exact money and ROI decimal strings in client types and UTC timestamps. Bet outcomes are open/won/lost/pushed/void; terminal evidence includes saved settlement status and final scores. Run summaries include current/available/final bankroll, realized profit/ROI, open/settled counts and wins/losses/pushes/voids. All client types for creation, replay, history and detail must share the extended shapes.

Run detail adds “Settle completed games”, disabled during submission and when the loaded Run is completed. Show that settlement uses saved game results and does not refresh providers. Replace both Run and Bets from the single POST response so metrics/outcomes are presented together. Show newly settled count and explain pending games (`game_not_final`, `final_scores_missing`) or the no-op case. An old game outside the current week can still be settled from stored results.

On transport failure, timeout or lost response, explain that the outcome could be saved and offer safe settlement retry plus reload of saved detail. Settlement uses terminal-state idempotency, not creation's stored Idempotency-Key. Preserve navigation cancellation/stale-response handling; a late response cannot change another Run. Do not apply optimistic profit updates. For completed Runs reached after response loss, reloading displays the saved completed result even though the action is disabled.

Replace the current unconditional “Results remain unsettled” text with explicit pending/partial/completed labels. Null means no settled results; exact zero means a settled zero result. Display final bankroll/end time only after completion, realized profit/ROI during partial settlement, open stake and available funds separately, outcome counts and Bet profit/settled time/result evidence. Render saved selection names, spreads, prices and provenance regardless of refreshed data. Show cancellation as void/stake returned and push as stake returned with zero profit. ROI ratios display as percentages using exact decimal-string formatting, including negative values, with no floating-point money arithmetic.

Dashboard shows simulation counts, summed independent simulation bankrolls, committed/available amounts, realized P&L/ROI, Bet outcome counts, at most ten recent results and cumulative realized profit over UTC settlement dates. Clearly label summed bankrolls as totals across independent simulations, without implying one wallet. Use a small accessible SVG line chart derived from the server performance series with a textual/table equivalent; include UTC date labels, negative/zero handling and empty/single-point states. Chart coordinates may use numeric conversions for drawing, but displayed/accounting values remain exact server strings. Recent results link to #/runs/{run_id}; loading/empty/error/retry states are required.

## Tasks

- [x] FE-01 — Add settlement and dashboard API clients
  - Status: complete
  - Scope: Extend shared Run/Bet types, add typed settlement/dashboard requests, bounded safe errors, abort support and exact ratio formatting.
  - Dependencies: Settled sibling backend contract; BE-02/BE-03 for real integration.
  - Acceptance criteria: POST has no score/outcome/body or creation request key; decimal strings/nulls/evidence are preserved; transport uncertainty and definite API errors have useful messages; ratios render exact percentages.
  - Validation: TypeScript/production build and intercepted browser contracts for methods, success/no-op/pending, 404/409/422/503, timeout, abort and signed/zero/null ROI formatting.
  - Completion notes: Implemented shared settlement/accounting types, bodyless settlement POST, dashboard GET, bounded errors, abort/timeout handling, exact ROI formatting, and intercepted browser contract tests. Whitespace check passed. Build/browser verification awaits the runner because Node/npm are unavailable and Docker access is denied. No protected files or Git state edited. Independent checks: Whitespace passed; Start sandbox database passed; Build current backend and fixture dependencies passed; Build isolated browser check image passed; Frontend build and controlled browser regressions passed. Files: frontend/src/api/dashboard.ts, frontend/src/api/results.ts, frontend/src/api/runs.ts, frontend/src/format.ts, frontend/tests/results-api.spec.ts, progress/1_4_mvp_vertical_slice_4/front_end/plan.md, ralph/slice4-frontend.progress.json. Logs: .git/ralph/244f409f1f7ebb13/FE-01-001.*. Provider keys remain blank. Controlled browser checks run for FE-01–FE-03; FE-04 additionally requires the real API and disposable PostgreSQL browser flow. Live-provider integration is separate.

- [ ] FE-02 — Add Run settlement and partial/final accounting views
  - Status: not_started
  - Scope: Extend Run detail and history with settlement action, returned outcome/evidence display, counts, realized metrics, final metrics and safe recovery.
  - Dependencies: FE-01; backend BE-02 for live behavior.
  - Acceptance criteria: One submission per action; action recovers after failure; partial/pending/completed/no-op states are distinct; zero is not mistaken for null; updated metrics and Bets come from the same POST response; reload/history preserve results; navigation prevents stale response corruption.
  - Validation: Controlled Playwright tests for all outcomes, known mixed-Run oracle, missing scores, no-op, disabled/double-click behavior, response loss/retry/reload, safe errors, route switch during POST, unchanged snapshots, keyboard focus/status and mobile overflow. Preserve creation/preview/history regression coverage.
  - Completion notes: Not implemented or validated.

- [ ] FE-03 — Add dashboard results and basic performance visualization
  - Status: not_started
  - Scope: Add #/dashboard navigation/page, server aggregate cards, recent-result links and accessible cumulative-profit chart/table.
  - Dependencies: FE-01; backend BE-03 for live behavior. May proceed alongside FE-02.
  - Acceptance criteria: Totals clearly represent independent simulations; realized ROI/profit are accurate; empty/loading/error/retry, negative/zero profit and UTC dates display correctly; recent results open saved Run history; chart is readable by keyboard/screen reader and at mobile width.
  - Validation: Build and browser fixtures for empty/partial/completed/multiple Runs, ratio units, daily cumulative values, single/negative/zero chart states, 10-result list, links/back/forward/reload, accessible equivalent and mobile layout.
  - Completion notes: Not implemented or validated.

- [ ] FE-04 — Prove the complete resolution flow without ingress
  - Status: not_started
  - Scope: Add live desktop/mobile browser acceptance using the guarded disposable backend fixture; document local settlement and accounting with backend BE-04.
  - Dependencies: FE-01–FE-03, backend BE-02–BE-04 fixture support.
  - Acceptance criteria: Create real Run before games complete, then inject controlled final scores only into its disposable Games, settle through production API, and independently verify persisted Bet outcomes/partial/final bankroll/ROI plus dashboard after reload. Lost response/retry causes no duplicate profit; historical snapshots survive quote changes; test artifacts clean up.
  - Validation: Production build, relevant controlled browser regressions, PostgreSQL-backed live flows at 375px/1280px, keyboard use and screenshot inspection. Exercise win/loss/push/void/pending with known fixtures; use whole-point or zero lines for pushes. Compare exact API/database values with displayed values and the backend plan's numeric oracle. Record provider final-score/Refresh integration as unperformed while ingress is absent.
  - Completion notes: Not implemented or validated.

## Epic acceptance and execution order

FE-01 → FE-02/FE-03 → FE-04; coordinate live validation with backend BE-04. Both sibling areas must complete their applicable tasks. The User can create a Run, settle confirmed stored results, inspect Bet history and partial/final P&L after reload, and view basic performance on Dashboard. Fixture score updates are test setup, not a production feature or proof of provider integration.

## Loop log

### 2026-10-03 — Slice 4 planning requested by CHIP

- Completed task IDs: None; all implementation tasks remain not_started.
- Validation: Reviewed governing designs, existing slice 3 plans and Run UI/API/error/retry patterns, and current disposable live backend helper. Checked sibling endpoints, accounting units, evidence, fixture scope, dependencies and required task fields. No application changes or runtime tests for this planning-only request.
- Blockers: None for the local-data slice. Actual provider final-score ingestion remains separately unimplemented; correction/regrading needs subsequent design authority.
- Next steps: FE-01 when implementation is requested, FE-02/FE-03 after client types, then FE-04 against the implemented backend. Existing plans and design documents remain unchanged.

### 2026-11-15 00:33 UTC — FE-01 Ralph execution

- Completed tasks: FE-01.
- Validation: Whitespace passed; Start sandbox database passed; Build current backend and fixture dependencies passed; Build isolated browser check image passed; Frontend build and controlled browser regressions passed.
- Completion notes: Implemented shared settlement/accounting types, bodyless settlement POST, dashboard GET, bounded errors, abort/timeout handling, exact ROI formatting, and intercepted browser contract tests. Whitespace check passed. Build/browser verification awaits the runner because Node/npm are unavailable and Docker access is denied. No protected files or Git state edited.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.
