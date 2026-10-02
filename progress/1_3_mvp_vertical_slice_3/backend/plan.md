# Design 1, part 3 — Dry Run Bets backend

Area status: `not_started`

Planning status: final implementation plan; implementation is not requested in this loop.

## Objective and governing design

Connect the existing Random Strategy → BetDecision boundary to a Dry Run adapter that atomically persists user-owned Runs and immutable theoretical Bets, with read APIs for inspection after reload.

- [MVP](../../../design/1_mvp.html), sections 3, 5–6, 8–9 (vertical slice 3), and 11.
- [Canonical ERD](../../../design/2_mvp_erd.png), User, Run, run_games, and Bet fields and relationships.
- [Ingress](../../../design/3_game_info_ingress.html), sections 2 and 6–7: server-clock eligibility, saved observations, immutable bets, and retained history.
- [Shared strategies](../../../design/4_shared_strategies.html): strategies are universal; Users continue to own Runs.
- [Completed slice 2](../../1_2_mvp_vertical_slice_2/backend/plan.md) and [frontend](../../1_2_mvp_vertical_slice_2/front_end/plan.md).
- [Separate ingress plan](../../3_1_game_info_ingress/backend/plan.md).
- [Sibling frontend plan](../front_end/plan.md).

## Current implementation and scope

Canonical Game/Market/Selection/Strategy models, shared strategy APIs, side-effect-free decision preview, and a Games-page preview UI exist. User, Run, run_games, Bet, and Dry Run execution do not exist. Ingress is planned but has no runtime models yet; demo quotes have null provenance.

Add persistence, execution, and inspection only. Settlement, results/P&L calculations, performance charts, dashboard aggregates, authentication, user management, additional strategy types, and provider ingestion are outside this slice. Preserve the existing preview flow. Creating a Run generates fresh server decisions; it does not place the previously displayed preview.

## Settled implementation contract

### Ownership and persistence

- Use one explicitly bootstrapped local simulation User for the existing local application. Add an idempotent `app.seed_user` command with stable UUID `50000000-0000-4000-8000-000000000001`, name `Local Simulator`, and email `simulator@autopredict.local`. Preserve an existing record. Resolve this user server-side; callers cannot submit `user_id`. This is local ownership plumbing, not an authentication boundary. No startup writes.
- Add a new additive Alembic revision after the current head, preserving prior revisions. Use ERD User/Run/run_games/Bet fields, UUIDs, UTC timestamps, existing timestamp conventions, foreign keys with restrictive deletion, and indexes on lookup relationships. Unique run/game association; preserve all requested games, including skipped games, in request order using an association position field and nullable skip reason.
- Run: non-null local `user_id` and selected `strategy_id`, optional name/notes, positive `starting_bankroll` and `stake_per_bet` as Numeric(12,2), `status: open`, execution `start_time`, nullable `end_time`, `final_bankroll`, `total_profit`, and `roi`. Settlement metrics remain null. Bankroll belongs to each independent simulation; there is no shared wallet across Runs.
- Bet: ERD fields plus immutable snapshot `game_id`, `market_id`, `side`, `line` Numeric(10,2), participant names, kickoff at placement, and nullable copied quote provenance (observation UUID, bookmaker, source timestamp, fetch time). Keep the Selection FK but render historical values from the snapshot. Price Numeric(10,4), stake Numeric(12,2), status `open`, and null result/profit/settled_at. One Bet per Run/game, enforced by uniqueness. Snapshot execution fields have no update API; settlement fields are reserved for slice 4.
- Add durable Run request UUID and normalized request payload/fingerprint with a unique local-user/request constraint for idempotent creation. Retain request identity with the Run, not in process memory.

### Creation and reads

- `POST /api/runs` body: `strategy_id` UUID, nonempty distinct `game_ids` UUID array, positive exact decimal strings `starting_bankroll` and `stake_per_bet`, optional nonblank `name` (max 255), optional `notes`. Reject extra fields, nonfinite values, excessive precision or Numeric(12,2) overflow with 422. Require UUID `Idempotency-Key` header; missing/malformed keys return 422.
- Validate every entity before sampling. Unknown strategy/game: 404; inactive strategy: 409; missing bootstrap User: sanitized 503 configuration detail. Reuse slice 2 eligibility/skip reasons and Random Strategy; no provider calls. At most one fresh decision per eligible game, preserving request order.
- Fixed stake applies to every generated Bet. Require `eligible_game_count * stake_per_bet <= starting_bankroll`; reject insufficient bankroll with 422 before sampling/persistence. Do not silently truncate games or adjust stakes. All-ineligible requests return 409 `No eligible games` and create nothing. Mixed requests persist eligible Bets and skipped requested games with their reasons.
- DryRunAdapter accepts typed server-generated BetDecision objects, a Run and fixed stake; it never chooses selections or calls providers. In one transaction lock requested games/markets/selections in stable UUID order, reread eligibility and quotes, generate decisions, then recheck server time immediately before insertion. If kickoff crosses during execution, drop that game's decision with the existing skip reason and rerun the budget/all-skipped checks. Hold locks through commit to prevent concurrent quote/status updates from producing inconsistent snapshots.
- Create User-owned Run, all run_games and Bets in one transaction; rollback all writes on failure. Same key and same normalized request return the original persisted result (200), without resampling or reevaluating current eligibility. Same key with different input returns 409. Concurrent same-key submissions converge on one Run through the unique constraint and a fresh transaction read after conflict. A new request key intentionally creates a separate simulation.
- New creation returns 201 with `{run, bets, skipped_games}`; replay returns the same shape with 200. Run includes ERD fields, `game_ids` in request order, `bet_count`, derived `committed_stake`, `available_bankroll` (starting minus open committed stakes in this slice), and saved skip reasons. Distinguish available bankroll from final bankroll or realized profit.
- `GET /api/runs`: local User's Runs, start_time descending then UUID ascending. `GET /api/runs/{run_id}`: same Run shape. `GET /api/runs/{run_id}/bets`: snapshot Bet array ordered by requested game position then Bet UUID. `GET /api/bets/{bet_id}`: one snapshot Bet. Scope reads to the resolved local User; shared Strategy discovery stays unchanged. Known empty lists return []; unknown resources return 404. UUID validation 422 and sanitized database failures 503 follow existing `detail` errors.
- All IDs are UUID strings, exact decimals are strings, timestamps UTC ISO 8601, and unset outcome/metrics are null. Reads never regenerate decisions, refresh providers, settle bets, or rewrite snapshots. Return stored game history even outside the current ingress window.
- If ingress exists when implementation starts, use its actual observation/invalidation schema and lock protocol in the same transaction. Provider-backed execution requires valid copied provenance; explicit demo records remain allowed with null provenance. No invented provenance or live-price claim. Ingress integration evidence is conditional on that separate implementation, not a blocker to the demo path.

## Tasks

- [ ] BE-01 — Persist local User, Runs, associations and snapshot Bets
  - Status: not_started
  - Scope: Add canonical models, additive migration, constraints/indexes, request identity storage, and explicit local User bootstrap described above.
  - Dependencies: Completed slice 2 models/migrations.
  - Acceptance criteria: ERD ownership and decimal precision preserved; Strategies remain shared; snapshots and skip associations survive reload; repeat bootstrap preserves edits; no startup writes; deletion cannot orphan history.
  - Validation: Disposable PostgreSQL migration upgrade/downgrade/re-upgrade and drift tests; constraints, FK retention, unique associations/idempotency key, nullable settlement fields, and repeated bootstrap.
  - Completion notes: Pending implementation and validation.

- [ ] BE-02 — Implement transactional Dry Run execution
  - Status: not_started
  - Scope: Add Run service and DryRunAdapter, reuse eligibility/random engine, apply fixed-stake budget checks, lock/revalidate stored quotes, and persist atomic snapshot execution.
  - Dependencies: BE-01.
  - Acceptance criteria: Exactly one open Bet per eligible game; mixed skips recorded; all-skipped/insufficient-budget requests write nothing; fresh server decisions only; no external calls; quote updates cannot mutate saved Bets; kickoff/inactive/invalidation checks apply at placement.
  - Validation: Deterministic strategy/adapter tests plus PostgreSQL rollback, exact budget boundary, frozen-clock cutoff, zero spread, mixed/all-skipped, invalid prices/pairs, and concurrent quote updates. Change Selection line/price after execution and assert historical Bet parity.
  - Completion notes: Pending implementation and validation; provider integration remains conditional on ingress availability.

- [ ] BE-03 — Expose idempotent Run creation and history APIs
  - Status: not_started
  - Scope: Add typed request/response schemas and five Run/Bet endpoints, local ownership resolution, durable replay handling, and documented error semantics.
  - Dependencies: BE-01–BE-02.
  - Acceptance criteria: Contract above is represented in OpenAPI; same-key retry returns one original Run even after kickoff/restart; changed-body reuse conflicts; exact decimals/null metrics/order survive reads; unrelated User history is unavailable; preview remains side-effect-free.
  - Validation: PostgreSQL API tests for 201/200, concurrent retries, retry after commit with lost response, replay after server restart and eligibility change, 404/409/422/503, ownership, query loading, CORS Idempotency-Key preflight, and existing API regressions.
  - Completion notes: Pending implementation and validation.

- [ ] BE-04 — Verify and document the persistence handoff
  - Status: not_started
  - Scope: Document migration/bootstrap, request key semantics, payloads and theoretical accounting labels; verify demo create/read/reload flow against PostgreSQL and hand off to frontend.
  - Dependencies: BE-01–BE-03; full epic acceptance also needs frontend FE-04.
  - Acceptance criteria: Documented local setup creates inspectable theoretical Bets; database history matches decisions and stake; replay creates no duplicates; snapshots survive quote changes; no settlement/P&L claimed.
  - Validation: Required backend regression suite with isolated PostgreSQL, migration drift, live HTTP create/replay/list/detail/bet smoke check using dedicated demo data, and frontend FE-04 browser evidence. Record unavailable provider integration explicitly.
  - Completion notes: Pending implementation and validation.

## Epic acceptance and execution order

BE-01 → BE-02 → BE-03 → BE-04; frontend client work may start against the settled contract. Both areas must pass their tasks: select games → create Random Strategy Dry Run → inspect persisted open Bets → reload and retrieve the same snapshots. No wagers or realized results are generated.

## Loop log

### 2026-10-01 — Slice 3 planning

- Completed task IDs: None; all implementation tasks remain not_started.
- Validation: Read governing designs including the ERD image, repository instructions, completed slice 2 plans, ingress plan, and current models/decision engine/schemas/frontend API client. Checked sibling contract and task dependencies. Runtime tests are not applicable to this planning-only change.
- Blockers: None for planning or the demo implementation path. Provider provenance integration awaits the separate ingress epic.
- Next steps: BE-01 when implementation is requested; frontend FE-01 may proceed against this contract.
