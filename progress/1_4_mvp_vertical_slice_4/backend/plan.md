# Design 1, part 4 — Settlement & P&L backend

Area status: `complete`

Planning status: ready. Current execution status and evidence are recorded in the task checklist and latest loop entries.

## Objective and governing design

Complete the persisted Dry Run path: explicitly settle eligible stored game results, preserve execution snapshots, and expose theoretical bankroll, realized P&L, ROI and dashboard summaries.

- [MVP](../../../design/1_mvp.html), sections 3–6, 8–9 (slice 4), and 11.
- [Canonical ERD](../../../design/2_mvp_erd.png), Game scores, Bet outcomes and Run metrics.
- [Ingress](../../../design/3_game_info_ingress.html), sections 2, 3, 6–7: explicit final confirmation, retained history, immutable Bets and separate on-demand refresh.
- [Shared strategies](../../../design/4_shared_strategies.html), shared Strategies with User-owned Runs.
- [Slice 3 backend](../../1_3_mvp_vertical_slice_3/backend/plan.md) and [frontend](../../1_3_mvp_vertical_slice_3/front_end/plan.md).
- [Separate ingress plan](../../3_1_game_info_ingress/backend/plan.md).
- [Sibling frontend plan](../front_end/plan.md).

## Current implementation and scope

User/Run/run_games/Bet persistence, atomic creation, durable creation retries and historical read APIs exist. Bets have immutable execution snapshots and reserved nullable settlement fields. Games already store status and scores. Run responses currently subtract open stakes from starting bankroll without realized profit; correct that when settlement lands. Run detail already renders nullable outcomes, but there is no settlement action, dashboard or performance display. Ingress remains independently unimplemented.

Implement settlement from canonical stored results, per-Run settlement action, accounting reads and a small dashboard. No provider requests, result editing API/UI, scheduler, background worker, shared wallet, authentication, strategy administration expansion or advanced analytics. This slice does not implement ingress or automatic correction/regrading of settled outcomes. Source corrections must remain audited by ingress; settled outcome correction needs subsequent design authority as required by design 3 section 6. Repeat settlement preserves the original result evidence and does not silently regrade it.

## Settled implementation contract

### Resolution and money

- Only `Game.status == completed` with both nonnegative integer scores resolves a spread. Scheduled/in_progress games and incomplete final records remain open, regardless of kickoff or elapsed time. A stored `canceled` game voids its open Bets and returns stake; canceled is an explicit source status, not a timeout inference.
- Use Bet.game_id and the saved Bet.side/line/price/stake, never refreshed Selection values. Match saved side to saved home_team/away_team; participant labels changed on Game must not change the selected side. Unexpected ambiguous snapshots fail the transaction with sanitized 409 instead of guessing.
- For a home Bet, adjusted margin = home_score - away_score + saved line; for an away Bet, away_score - home_score + saved line. Positive is `won`, negative `lost`, zero `pushed`. Terminal Bet.status and result use ERD values `won`, `lost`, `pushed`, `void`.
- Decimal arithmetic only. Winning net profit = stake * (decimal price - 1), rounded once per Bet to cents using ROUND_HALF_UP; loss = -stake; push/void = 0.00. Returned stake is not profit. Aggregate the stored rounded Bet profits, never round an aggregate of unrounded payouts.
- Run `total_profit` stays null until its first settlement, then is realized profit across terminal Bets even while the Run is open. `committed_stake` = sum of open stakes. `available_bankroll` = starting_bankroll + realized profit - committed_stake, using zero realized profit before any settlement. Add `current_bankroll` = starting_bankroll + realized profit, plus `open_bet_count`, `settled_bet_count`, `win_count`, `loss_count`, `push_count`, `void_count`, and `settled_stake` (includes all terminal Bets).
- ROI is a ratio: total_profit / starting_bankroll, rounded to four decimal places with ROUND_HALF_UP; null before first settlement. The frontend displays it as a percentage. A partially settled Run exposes realized ROI and profit, with final_bankroll/end_time still null. When every recorded Bet is terminal, status becomes `completed`, final_bankroll = current_bankroll, and end_time = settlement execution time. Skipped requested games never hold a Run open or count as Bets. Zero-profit settlements expose zero, not null.
- Add settlement evidence to Bet: nullable settlement_home_score, settlement_away_score, settlement_game_status. Require evidence/status/profit/settled_at consistency for terminal Bets and null evidence/outcomes for open Bets. Canceled evidence may have null scores. This is stored result evidence, not an alteration of execution snapshots. Add an additive migration after the actual existing head; retain schema precision and reject calculated Numeric overflow with 409 and no writes. Large valid execution prices can otherwise exceed existing profit/ROI precision.

### Execution and APIs

- `POST /api/runs/{run_id}/settle` accepts no body and reads stored results only. Resolve the existing local User server-side and require ownership, returning 404 for unknown/other-user Runs, 422 for malformed UUID or unexpected body, sanitized 503 for configuration/database failure, and 409 for invalid snapshot or accounting overflow. No caller-supplied scores, outcomes, user IDs or profit.
- Return HTTP 200 with `{run, bets, settled_bet_ids, pending_games}`. Run and ordered Bets use the extended existing read shapes. IDs are ordered by requested game position then Bet UUID. pending_games contains only games with open Bets, each `{game_id, reason}` where reason is `game_not_final` or `final_scores_missing`. Completed games with missing scores remain pending. An all-pending or already-completed Run returns 200 with an empty settled_bet_ids array; this is a valid no-op.
- In one transaction, lock referenced Games in stable UUID order, then Run, then its Bets in UUID order; refresh previously loaded state after lock waits. Reread all stored outcomes. Settle only open Bets and recompute aggregates before one commit. Failure rolls back every newly settled Bet and all Run metrics. This ordering agrees with slice 3 creation's Game-before-Bet writes and leaves ingress free to lock Games without acquiring Runs. No Market/Selection writes or locks are needed.
- Repetition and concurrent submissions must not credit money twice. Terminal state is the durable idempotency boundary; no settlement Idempotency-Key is required. A retry can also settle a game that newly became final; it returns current persisted state, not a cached prior response. Lost-response recovery is safe through repeat POST or history reads. Completed Run end_time, settled_at, profit and evidence remain unchanged on no-op retries.
- GET endpoints remain read-only; page loads and reads do not settle. Extend all Run/Bet reads and creation/replay responses consistently; preserve ordering, ownership, decimal strings, UTC times, saved skips and quote provenance. A creation-key replay after settlement returns the same Run/Bets with their current outcomes and creates no new simulation.
- `GET /api/dashboard` reads local-user simulations only, returning `{run_count, active_run_count, completed_run_count, starting_bankroll_total, current_bankroll_total, available_bankroll_total, committed_stake_total, realized_profit, roi, bet_count, open_bet_count, win_count, loss_count, push_count, void_count, recent_results, performance}`. Bankroll totals sum independent simulations and must be labeled accordingly; there is no shared cash account. Overall ROI = summed realized profit / summed starting bankroll, four decimal ratio, null with no Runs. Empty sums/counts are zero.
- recent_results contains at most 10 terminal Bet responses ordered settled_at descending then Bet UUID. performance is cumulative realized profit grouped by UTC settlement date in ascending order, `{date, profit, cumulative_profit}` with exact decimal strings; it is empty before settlement. Aggregate across all owned history, without the ingress current-week filter. Read without N+1 queries and within one consistent database snapshot; do not combine dashboard aggregates from different committed states.

## Test resolution before provider updates

Provider result availability is not a prerequisite for deterministic resolution testing. Reuse `backend/tests/conftest.py` and `frontend/tests/support/live_backend.py` generated disposable PostgreSQL databases. Seed explicitly fictional upcoming games, shared strategy and local User; create real Runs through POST /api/runs before marking games final. Then update only those disposable Games with controlled completed/status/score fixtures using a test helper. Invoke the production settlement API and inspect persisted outcomes and browser presentation. The helper must enforce the generated database-name guard, require known Run/Game IDs, and remove database/server/metadata artifacts on exit. Do not add test score-writing endpoints to the production application, mutate development/provider games, or repurpose the ordinary demo bootstrap as an outcome updater.

Control randomness in unit/service tests. In browser acceptance, inspect the actually persisted Bet side and line, then choose final scores to force independently calculated win/loss/push outcomes. Use dedicated zero/integer-line selections for a possible push; integer football scores cannot push a half-point line. Include home/away choices, favorite/underdog, zero lines, equal scores, price four-decimal precision and half-cent rounding. Test canceled voids and missing-final-score cases separately. Tests must assert known numeric expected results, not simply recompute production formulas with the same code.

Independent mixed-Run oracle: bankroll 100.00, four stakes of 10.00; one win at 1.9500, one loss, one push and one pending Bet gives realized profit -0.50, committed 10.00, available 89.50, current bankroll 99.50, ROI -0.0050, and null final_bankroll/end_time. Voiding the remaining Bet completes the Run with final_bankroll 99.50, committed 0.00 and available 99.50. Repeat settlement must preserve all values and timestamps. This covers the user-visible flow without waiting for real games or provider updates. Actual CFBD final-confirmation ingestion remains a separately recorded, unperformed integration until ingress lands.

## Tasks

- [x] BE-01 — Add settlement evidence and pure spread accounting
  - Status: complete
  - Scope: Add additive evidence migration/constraints and a pure Decimal resolver using the contract above.
  - Dependencies: Completed slice 3 schema.
  - Acceptance criteria: Deterministic home/away win/loss/push/void resolution from saved execution fields; incomplete games stay pending; rounding and evidence consistency hold; malformed snapshots/overflow cannot persist.
  - Validation: Table-driven known-result unit tests, half-cent boundaries, zero/negative spreads, null scores, cancellation, changed quote/team labels; disposable PostgreSQL upgrade/downgrade/re-upgrade and Alembic drift/constraint checks.
  - Completion notes: Implemented additive settlement evidence migration/constraints, pure Decimal spread resolution, and unit/PostgreSQL tests. Focused checks: 38 passed; whitespace passed. PostgreSQL checks await runner verification because Docker access is denied; broader local suite was interrupted. No plan, design, runner, or Git-state edits. FE-04 browser evidence remains pending. Independent checks: Whitespace passed; Start sandbox database passed; Build backend dependencies passed; Backend regressions with disposable PostgreSQL databases passed. Files: backend/app/models.py, backend/app/settlement.py, backend/tests/test_ingress_persistence.py, backend/tests/test_settlement.py, backend/tests/test_settlement_persistence.py, migrations/versions/0005_add_settlement_evidence.py, progress/1_4_mvp_vertical_slice_4/backend/plan.md, ralph/slice4-backend.progress.json. Logs: .git/ralph/64d424df51d8dd0a/BE-01-001.*. Backend verification only; full-epic live browser acceptance is performed later by frontend FE-04. No live-provider verification is implied.

- [x] BE-02 — Implement atomic per-Run settlement and extended history
  - Status: complete
  - Scope: Add settlement service, POST route, evidence responses, accurate partial/final Run metrics and extended existing serializers.
  - Dependencies: BE-01.
  - Acceptance criteria: Owned stored results settle once; partial/no-op/retry behavior matches contract; completed timestamps remain stable; snapshots/creation identity remain immutable; transactional rollback prevents partial credit.
  - Validation: PostgreSQL API tests for mixed oracle, all-pending/missing scores/canceled/skipped games, independent Runs on one game, concurrent same-Run POSTs, score-writer locking, injected failure rollback, overflow, lost response/restart retry, ownership, 404/409/422/503, OpenAPI and creation replay after settlement. Prove GET calls issue no writes.
  - Completion notes: Implemented atomic settlement, extended Run/Bet history, and PostgreSQL regression tests covering accounting, retries, concurrency, locking, and rollback. Syntax and whitespace checks passed. Docker access denied locally; runner verification required. FE-04 browser evidence remains pending. No protected files or Git state changed. Independent checks: Whitespace passed; Start sandbox database passed; Build backend dependencies passed; Backend regressions with disposable PostgreSQL databases passed. Files: backend/app/routes.py, backend/app/runs.py, backend/app/schemas.py, backend/tests/test_run_settlement.py, progress/1_4_mvp_vertical_slice_4/backend/plan.md, ralph/slice4-backend.progress.json. Logs: .git/ralph/64d424df51d8dd0a/BE-02-002.*. Backend verification only; full-epic live browser acceptance is performed later by frontend FE-04. No live-provider verification is implied.

- [x] BE-03 — Add persisted dashboard aggregates
  - Status: complete
  - Scope: Implement GET /api/dashboard with consistent local-user totals, recent results and UTC daily cumulative performance.
  - Dependencies: BE-02.
  - Acceptance criteria: Empty/partial/completed histories yield exact documented totals; unrelated User data is excluded; no provider calls or current-week filtering; aggregate ROI uses total starting bankroll rather than an average of Run ROIs.
  - Validation: PostgreSQL known-total fixtures for multiple independent Runs, zero profit, no Runs, UTC date boundaries, tie ordering/10-result limit, ownership, snapshot consistency and bounded query count.
  - Completion notes: Implemented snapshot-consistent dashboard totals, recent results, and UTC cumulative performance with PostgreSQL coverage. Whitespace and Python syntax checks passed. Runtime tests await runner verification: Docker access is denied and local Python dependencies are unavailable. No plan, progress, or Git state edits performed. Independent checks: Whitespace passed; Start sandbox database passed; Build backend dependencies passed; Backend regressions with disposable PostgreSQL databases passed. Files: backend/app/dashboard.py, backend/app/routes.py, backend/app/schemas.py, backend/tests/test_dashboard.py, progress/1_4_mvp_vertical_slice_4/backend/plan.md, ralph/slice4-backend.progress.json. Logs: .git/ralph/64d424df51d8dd0a/BE-03-003.*. Backend verification only; full-epic live browser acceptance is performed later by frontend FE-04. No live-provider verification is implied.

- [x] BE-04 — Validate and document the full resolution handoff
  - Status: complete
  - Scope: Extend guarded disposable browser fixture support for final scores; document accounting, settlement requests/retries, fixture use and provider limitations in README.
  - Dependencies: BE-01–BE-03; full epic acceptance also requires frontend FE-04.
  - Acceptance criteria: Real API create → fixture finalization → settle → read/reload produces independently verified P&L without live ingress; no development mutations or generated artifacts remain; frontend has reproducible evidence.
  - Validation: Required backend regression suite with RUN_POSTGRES_TESTS=1, migration drift, actual HTTP smoke plus frontend FE-04 evidence; inspect fixture guard and cleanup. Provider final-confirmation integration is conditional and explicitly unperformed while ingress is absent.
  - Completion notes: Added guarded settlement fixtures, deterministic real HTTP acceptance tests, and concise README handoff documentation. Focused checks: 41 passed, 1 skipped; whitespace clean. Docker access denied locally, so PostgreSQL verification awaits the runner. FE-04 browser evidence remains pending. No Git or progress edits performed. Independent checks: Whitespace passed; Start sandbox database passed; Build backend dependencies passed; Backend regressions with disposable PostgreSQL databases passed. Files: README.md, backend/tests/test_resolution_handoff.py, frontend/tests/support/live_backend.py, progress/1_4_mvp_vertical_slice_4/backend/plan.md, ralph/slice4-backend.progress.json. Logs: .git/ralph/64d424df51d8dd0a/BE-04-007.*. Backend verification only; full-epic live browser acceptance is performed later by frontend FE-04. No live-provider verification is implied.

## Epic acceptance and execution order

BE-01 → BE-02 → BE-03 → BE-04. Frontend FE-01 may begin from this settled contract; live acceptance requires the implemented API. Both sibling areas must complete applicable tasks. A User can create a theoretical Run, settle stored confirmed results, inspect partial/final bankroll and exact Bet P&L after reload, and see dashboard totals/performance. Provider refresh remains independent; no claim of live-result integration is necessary to complete the fictional local-data slice.

## Loop log

### 2026-10-03 — Slice 4 planning requested by CHIP

- Completed task IDs: None; all implementation tasks remain not_started.
- Validation: Read repository instructions, governing design documents and ERD, prior slice plans, current models/schemas/routes/Run accounting, frontend history/client and disposable database/browser fixtures. Checked sibling contract/dependencies and plan format/links; no runtime tests executed for this documentation-only change.
- Blockers: None for local-data implementation. Provider ingress/results integration is absent and must be recorded separately. Settled score correction/regrading remains outside this slice under design 3 section 6.
- Next steps: BE-01 when implementation is requested; then BE-02 and frontend FE-01. Existing plans, design files and application code remain unchanged.

### 2026-11-14 23:42 UTC — BE-01 Ralph execution

- Completed tasks: BE-01.
- Validation: Whitespace passed; Start sandbox database passed; Build backend dependencies passed; Backend regressions with disposable PostgreSQL databases passed.
- Completion notes: Implemented additive settlement evidence migration/constraints, pure Decimal spread resolution, and unit/PostgreSQL tests. Focused checks: 38 passed; whitespace passed. PostgreSQL checks await runner verification because Docker access is denied; broader local suite was interrupted. No plan, design, runner, or Git-state edits. FE-04 browser evidence remains pending.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.

### 2026-11-14 23:45 UTC — BE-02 Ralph execution

- Completed tasks: BE-02.
- Validation: Whitespace passed; Start sandbox database passed; Build backend dependencies passed; Backend regressions with disposable PostgreSQL databases passed.
- Completion notes: Implemented atomic settlement, extended Run/Bet history, and PostgreSQL regression tests covering accounting, retries, concurrency, locking, and rollback. Syntax and whitespace checks passed. Docker access denied locally; runner verification required. FE-04 browser evidence remains pending. No protected files or Git state changed.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.

### 2026-11-14 23:48 UTC — BE-03 Ralph execution

- Completed tasks: BE-03.
- Validation: Whitespace passed; Start sandbox database passed; Build backend dependencies passed; Backend regressions with disposable PostgreSQL databases passed.
- Completion notes: Implemented snapshot-consistent dashboard totals, recent results, and UTC cumulative performance with PostgreSQL coverage. Whitespace and Python syntax checks passed. Runtime tests await runner verification: Docker access is denied and local Python dependencies are unavailable. No plan, progress, or Git state edits performed.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.

### 2026-11-15 00:30 UTC — BE-04 Ralph execution

- Completed tasks: BE-04.
- Validation: Whitespace passed; Start sandbox database passed; Build backend dependencies passed; Backend regressions with disposable PostgreSQL databases passed.
- Completion notes: Added guarded settlement fixtures, deterministic real HTTP acceptance tests, and concise README handoff documentation. Focused checks: 41 passed, 1 skipped; whitespace clean. Docker access denied locally, so PostgreSQL verification awaits the runner. FE-04 browser evidence remains pending. No Git or progress edits performed.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.
