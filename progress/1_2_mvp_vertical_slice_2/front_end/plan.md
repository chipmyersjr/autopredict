# Design 1, part 2 — Random Strategy frontend

Area status: `complete`

Planning status: final implementation plan. CHIP’s shared-strategy decision is resolved; frontend implementation and validation are complete; backend BE-02–BE-06 are complete.

## Objective and governing design

Extend the Games page so the user can select games, execute the Random Strategy, and inspect generated spread decisions and reasons for skipped games.

- [MVP](../../../design/1_mvp.html), sections 5–6, 8–9 (vertical slice 2), and 11.
- [Shared strategies](../../../design/4_shared_strategies.html): CHIP’s accepted universal strategy scope; supersedes Strategy ownership in design 1.
- [ERD](../../../design/2_mvp_erd.png), Strategy and canonical selection identities.
- [Ingress design](../../../design/3_game_info_ingress.html), sections 2 and 6–7: stored snapshots, kickoff cutoff, demo separation and simple Refresh flow.
- [Completed slice 1 frontend](../../1_1_mvp_vertical_slice_1/front_end/plan.md).
- [Ingress frontend](../../3_1_game_info_ingress/front_end/plan.md), separate Refresh work.
- [Sibling backend plan](../backend/plan.md), final shared implementation contract.

## Current implementation and scope

The Games page already fetches nested games, displays spread selections, handles loading/error/empty states, and preserves latest-kickoff-first ordering. It has no game selection or strategy execution controls. Reuse the existing page, API base URL, styling and Playwright setup.

Slice 2 displays decision previews. Saved Runs, theoretical Bets, stake/bankroll inputs, bet history, settlement and P&L remain later slices. Display the universally available baseline Random Strategy and an execution action without user-ownership filtering; broader strategy administration UI is not needed to demonstrate this slice.

The shared implementation contract is in the backend plan: strategy discovery through the design strategy read API, a POST decision-preview endpoint receiving selected game IDs, exact decimal-string decisions, and explicit per-game skips. Implement client types and error handling to match that contract and verify parity with OpenAPI during integration.

Client eligibility can guide selection, but the server rechecks at execution time. Opening the page and executing the strategy do not invoke provider refresh. Preserve demo labeling; support ingress current-week reads/Refresh when that separate epic lands. Avoid duplicate Refresh controls or quota/status panels.

## Tasks

- [x] FE-01 — Add typed strategy and decision API client
  - Status: complete
  - Scope: Add strategy discovery and preview request/response types, exact decimal strings, abort support and safe errors using the existing API base URL.
  - Dependencies: Shared backend implementation contract; BE-02/BE-05 for live integration.
  - Acceptance criteria: Client sends canonical selected IDs to the backend; parses decisions/skips without calculating random outcomes or changing line/price precision; supports failure and request cancellation; providers are never called directly.
  - Validation: Type/build checks and Playwright request interception validating methods, body, success/skip/error handling. Actual backend parity verified in FE-04.
  - Completion notes: Added src/api/strategies.ts with typed strategy/preview contracts, AbortSignal support, POST game_ids and bounded HTTP errors. Production TypeScript/Vite build and intercepted request tests passed.

- [x] FE-02 — Add game selection and Random Strategy action
  - Status: complete
  - Scope: Add labeled game checkboxes, selected count, baseline strategy display and an execution button to the existing Games page. Guide selection using known eligibility and prevent duplicate in-flight submissions.
  - Dependencies: FE-01; shared backend eligibility policy.
  - Acceptance criteria: User can select/deselect multiple games; empty selection or unavailable/inactive strategy disables execution; known ineligible games explain why they cannot participate; selected IDs are submitted once per action; controls recover after failure; existing game display/order and Refresh behavior remain usable.
  - Validation: Browser tests for multi-game selection, missing spreads, closed/inactive records, known kickoff cutoff, strategy loading/absence/errors, keyboard labels/focus, disabled action and double-click protection.
  - Completion notes: GamesPage.tsx adds labeled checkboxes, eligibility guidance with a ticking kickoff clock, baseline strategy discovery/retry, selected count and guarded execution. Browser tests cover multi-selection, inactive/absent/failed strategy, cutoff, invalid/inactive pairs, keyboard selection and in-flight protection.

- [x] FE-03 — Display decision previews and skip outcomes
  - Status: complete
  - Scope: Render generated team/spread/decimal-price decisions and per-game skips with execution timestamp, safe error and all-skipped states. Label results as decisions; show available saved quote provenance without inventing it.
  - Dependencies: FE-02; backend BE-05 for live behavior.
  - Acceptance criteria: Decisions correspond to the submitted games and response IDs; signed/zero lines and exact prices render correctly; skipped games are explained; changed selection, reloads and repeated execution cannot leave results falsely attributed to a newer request; late responses cannot overwrite current results. No bet placement, persisted-run or profit claims.
  - Validation: Controlled responses for success, mixed/all-skipped, 404/422/503/transport failures, abort/stale completion, changed selection and repeated execution; keyboard/live status and mobile overflow checks. Preserve existing Games-page tests.
  - Completion notes: GamesPage.tsx renders decisions, exact prices, signed/zero lines, timestamp, optional saved provenance and explicit skips. Changing selection aborts pending work and clears results. Browser tests passed for mixed/all-skipped, HTTP and transport recovery, keyboard execution and stale-response cancellation.

- [x] FE-04 — Validate complete browser flow and document it
  - Status: complete
  - Scope: Verify real frontend/backend select → execute → inspect flow with explicitly labeled seeded games; document setup and review evidence alongside backend BE-06.
  - Dependencies: FE-01–FE-03 and backend BE-05. Backend BE-06 is complete with HTTP/API evidence; perform the full UI browser validation here.
  - Acceptance criteria: Live backend decides the returned selections; displayed exact values match response snapshots; a game becoming ineligible before submission is skipped by server; retry recovers; Games-page regressions pass; no Run/Bet writes or provider refresh occurs. Desktop/mobile and keyboard use remain readable and operable.
  - Validation: Frontend build/type checks, relevant Playwright regression/interaction suite, and live PostgreSQL-backed browser smoke test using dedicated data where practical. Inspect screenshots and record browser coverage. If ingress is available, verify current-week/Refresh/provenance compatibility; otherwise explicitly record that integration as unperformed.
  - Completion notes: Added strategies-live.spec.ts and isolated test-port configuration. Chrome live tests passed at 375px and 1280px against PostgreSQL-backed API on port 8004; all four eligible demo games generated exact snapshot decisions. Screenshots inspected with no overflow. README documents setup and test commands. Provider integration remains unperformed.

## Frontend and epic acceptance criteria

The user selects stored games, executes the Random Strategy once, and sees generated decisions plus skips. Exact spread/price values are preserved; stale responses cannot corrupt the view; errors recover and keyboard/mobile access works. Both sibling areas must complete validation before the epic is complete. This slice does not claim Dry Run bets or settlement.

## Loop log

### 2026-10-01 — Slice 2 planning requested by CHIP

- Completed task IDs: None; planning only.
- Validation: Reviewed design 1/3, ERD, existing Games page/API client, slice 1 and ingress plans, and backend implementation. Matched FE-01–FE-04 to BE-01–BE-06; no UI code, dependency changes or runtime checks performed.
- Blockers: No planning blocker. Live implementation needs finalized backend contracts and POST access; provider integration stays in the ingress epic.
- Next steps: Finalize backend BE-01, then FE-01 and FE-02. Leave every implementation task unchecked until its acceptance criteria and validation pass.

### 2026-10-01 — Planning behavior corrected by CHIP

- Completed task IDs: None.
- Changes: Removed dependencies on the retired backend planning task; reference the concrete shared contract instead.
- Validation: Reviewed task dependencies and contract alignment; no UI implementation or runtime checks.
- Blockers: Shared ownership discussion is active with CHIP; this remains a blocked draft rather than a final plan. Earlier deferral instructions are superseded by this entry.
- Next steps: Incorporate the resolved ownership contract before finishing planning; then FE-01 when implementation is requested.

### 2026-10-01 — Shared strategies accepted by CHIP; planning finalized

- Completed task IDs: None; implementation remains not started.
- Changes: Referenced design/4_shared_strategies.html, recording CHIP’s decision that Strategies are universal with per-user custom strategies deferred. Removed active planning blockers and retained stable implementation IDs and historical loop entries.
- Validation: Governing design and sibling contracts agree on shared visibility and no Strategy ownership field; links and required task fields checked. No application changes or runtime tests.
- Blockers: None for planning. Earlier ownership-blocker entries are resolved by this decision.
- Next steps: BE-02/BE-03 for backend and FE-01 for frontend when implementation is requested.

### 2026-10-01 — Completed backend handoff

- Completed frontend task IDs: None; area remains not_started. Backend BE-02–BE-06 are complete.
- Contract: GET/POST /api/strategies, GET /api/strategies/{strategy_id}, POST /api/strategies/{strategy_id}/decisions. Shared baseline UUID: 40000000-0000-4000-8000-000000000001. Preview accepts distinct game_ids and returns decisions/skipped_games with exact decimal strings and server-clock eligibility; demo quote_provenance is null.
- Validation: Backend suite passed 64 PostgreSQL checks; live API/CORS/OpenAPI and exact snapshot parity passed on http://127.0.0.1:8003. GET/POST plus Content-Type supported for configured local origins. No frontend implementation or browser rendering validation performed.
- Limitations: Provider ingress/provenance integration remains unimplemented. Frontend FE-04 must validate the actual select/execute/render flow; backend-only delivery does not mark this epic complete.
- Blockers: None for frontend integration; verify server availability when starting.
- Next steps: FE-01 against the implemented OpenAPI schemas, then FE-02–FE-04 when requested.

### 2026-10-01 — Backend handoff reverified

- Completed frontend task IDs: None; area remains not_started.
- Validation: Backend implementation reviewed and all 64 tests passed against disposable PostgreSQL databases. Existing shared API contract is unchanged; no frontend code changes were needed for this backend-only request.
- Blockers: None for frontend integration. Provider ingress/provenance and full browser rendering remain unvalidated here.
- Next steps: FE-01–FE-04 when frontend implementation is requested.

### 2026-10-01 — Frontend implemented and validated

- Completed task IDs: FE-01–FE-04. Both backend and frontend areas are complete for the demo Random Strategy slice.
- Affected files: frontend/src/api/strategies.ts, src/pages/GamesPage.tsx, src/styles.css, tests/games.spec.ts, tests/strategies.spec.ts, tests/strategies-live.spec.ts, playwright.config.ts; README.md and sibling plans.
- Validation: Production TypeScript/Vite build passed. Chrome regression suite passed 21 tests with 3 opt-in live tests skipped. Separate live decision suite passed 2 tests at 375px/1280px using existing demo PostgreSQL data, isolated frontend 5176 and backend 8004 with matching CORS. Exact line/price parity and mobile overflow assertions passed; both screenshots inspected. Backend SELECT-only preview evidence remains applicable; frontend requests only stored games, strategy discovery and preview.
- Cutoff evidence: Browser clock test crosses kickoff after selection and displays the authoritative mocked server skip. Real server cutoff is covered by backend frozen-clock/PostgreSQL tests; live browser smoke did not change kickoff in the development database.
- Limitations: Ingress current-week/Refresh and real provider provenance are not implemented; nullable provenance rendering tested with controlled data only. Existing demo labels remain visible.
- Blockers: None for this slice.
- Next steps: Dry Run execution in a later MVP part; provider integration in its separate ingress epic.
