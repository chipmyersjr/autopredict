# Design 1, part 2 — Random Strategy backend

Area status: `complete`

Planning status: final implementation plan. CHIP’s shared-strategy decision is resolved; backend implementation and backend validation are complete; frontend implementation and browser validation are now complete.

## Objective and governing design

Let the user select stored games and execute the Random Strategy to receive spread betting decisions. Preserve the Strategy → BetDecision boundary so slice 3 can send those decisions to the Dry Run adapter.

- [MVP](../../../design/1_mvp.html), sections 2–3, 5–6, 9 (vertical slice 2), and 11.
- [Shared strategies](../../../design/4_shared_strategies.html): CHIP’s accepted universal strategy scope; supersedes Strategy ownership in design 1.
- [ERD](../../../design/2_mvp_erd.png), strategy fields and relationships.
- [Ingress design](../../../design/3_game_info_ingress.html), sections 2, 5–7: saved quotes, eligibility at kickoff, provider separation, and immutable future bets.
- [Slice 1 backend](../../1_1_mvp_vertical_slice_1/backend/plan.md) and [frontend](../../1_1_mvp_vertical_slice_1/front_end/plan.md), completed games/spreads foundation.
- [Ingress backend](../../3_1_game_info_ingress/backend/plan.md), separately planned provider/provenance work.
- [Sibling frontend plan](../front_end/plan.md).

## Current implementation and scope

Game/Market/Selection persistence, demo seeding, nested read APIs, and the Games page exist. Slice 2 backend now adds the shared Strategy model, APIs, baseline loader, eligibility resolver and Random Strategy engine. CORS allows GET/POST with Content-Type. User, Run, Bet, provider ingestion and the slice 2 UI remain unimplemented.

This slice adds the Random Strategy and decision preview. Run persistence, run-game associations, bankroll/stake accounting, Dry Run execution, bets, settlement, and P&L remain slices 3–4. Provider ingestion stays in design 3 part 1; executing a strategy reads stored data and never refreshes providers.

## Implementation contract

The following implementation choices are settled within the governing design. Strategies are shared across all users, with no `user_id` or ownership filter. User-owned custom strategies remain future design work; slice 2 requires no User table or authentication implementation.

- Persist the baseline Random Strategy using the ERD fields and an explicit idempotent bootstrap command. Reuse explicit migration/seed patterns; no startup writes. Implement design section 6 strategy list/create/detail endpoints for the supported `random` type only.
- Use `POST /api/strategies/{strategy_id}/decisions` with a nonempty list of distinct game UUIDs. This previews decisions; it is not `POST /api/runs` and creates no Run or Bet.
- Generate one unbiased random choice among eligible spread selections per selected game. Eligibility: scheduled game with known future kickoff, active spread market, active selection, valid team side, finite non-null line, and finite decimal price greater than one. Respect ingress pairing/invalidation and saved-quote availability when that integration exists; retain the ability to exercise the slice with explicitly labeled demo fixtures.
- Use canonical IDs and exact decimal strings. Return strategy ID, decision timestamp, requested game IDs, decisions (game/market/selection IDs, team side, signed line, decimal price), and per-game skip reasons. Copy existing quote provenance when available; never fabricate provider provenance for demos. No stake or bankroll is needed for this preview.
- Unknown strategy/game IDs reject the request before generation; malformed IDs and invalid input receive validation errors. Known ineligible games produce explicit skips, including an all-skipped response. Use sanitized database failures consistent with existing APIs.
- Keep random generation injectable for deterministic tests. The browser does not choose selections. Sort candidate IDs before sampling so test behavior does not depend on ORM/provider ordering.

### API and selection details

- Strategy responses expose `id`, `name`, `type`, `description`, `is_active`, `config`, `created_at`, and `updated_at`; no ownership field is accepted or returned. Create accepts a nonempty name, optional description, `type: "random"`, `is_active` (default true), and null or empty-object config. Reject unsupported configuration. The explicit bootstrap creates one stable-ID active baseline named “Random Strategy” and preserves existing records.
- Preview body: `{"game_ids": ["<uuid>"]}`. Reject empty or duplicate IDs with 422. Response: `strategy_id`, `generated_at` (UTC), `requested_game_ids`, `decisions`, and `skipped_games`. Each decision contains `game_id`, `market_id`, `selection_id`, `side`, `line`, `price`, and nullable `quote_provenance`; each skip contains `game_id` and `reason`. Preserve request game order in results; sort candidates by market/selection UUID before uniform sampling.
- Eligible markets contain exactly two active selections matching distinct home/away teams, finite opposite lines (including zero), and valid prices. Sample uniformly from all selections in valid active spread markets, with one decision per eligible game. Skip precedence: `game_not_scheduled`, `kickoff_reached`, `spread_unavailable`. Unknown kickoff is unavailable. Source-confirmed cancellation/postponement or ingress invalidation blocks candidates.
- Return 200 for success, mixed skips, and all-skipped responses; 404 for an unknown strategy or requested game; 409 for an inactive strategy; 422 for invalid request data; sanitized 503 for database failure. Validate every requested ID before drawing any random choice. Errors use the existing FastAPI `detail` convention.
- `quote_provenance` is null for demo data; provider-backed decisions copy the ingress observation identity, bookmaker, source timestamp when supplied, and fetch timestamp. Provider integration must use the concrete ingress schema when available; missing observation data never becomes fabricated provenance.

## Tasks

BE-01 is retired: its former “Finalize strategy and decision contracts” task improperly deferred planning. Remaining task IDs are preserved. Contract decisions are recorded above; CHIP resolved shared Strategy scope in design 4.

- [x] BE-02 — Persist and expose the Random Strategy
  - Status: complete
  - Scope: Add Strategy model/new Alembic revision, explicit idempotent baseline loader, and list/create/detail endpoints. Validate supported type/configuration and inactive strategies.
  - Dependencies: Completed slice 1.
  - Acceptance criteria: PostgreSQL stores ERD strategy fields without `user_id`; strategies are universally discoverable and executable; repeat bootstrap preserves existing records; read/create contracts are documented; unsupported types/configuration are rejected; no Run/Bet tables or automatic seeding.
  - Validation: Disposable PostgreSQL migration/constraint/API tests, repeated bootstrap, valid/invalid configuration, missing/malformed IDs, and sanitized database errors. Preserve existing migration history.
  - Completion notes: Added Strategy in backend/app/models.py, migration 0002, strategy schemas/read-create routes, and app/seed_strategy.py. PostgreSQL tests verify JSONB config/type/name constraints, shared visibility, no ownership field, 201 creation, missing/malformed IDs and repeat bootstrap preserving edited/inactive records. Migration cycle/drift checks pass.

- [x] BE-03 — Resolve eligible stored selections
  - Status: complete
  - Scope: Build a database-backed candidate resolver using server time and existing canonical models; return bounded per-game skip reasons and available snapshot data.
  - Dependencies: Completed slice 1 models/read contracts. Ingress provenance integration depends on ingress BE-09/BE-11 when available.
  - Acceptance criteria: Only requested games participate; no provider calls; cutoff applies even if stored status still says scheduled; closed/inactive/invalid selections cannot participate; zero line is valid; each participating market must have exactly two active selections matching the game’s teams with opposite lines; candidates from all valid active spread markets are sampled uniformly, producing one decision per game.
  - Validation: Frozen-clock tests just before/at/after kickoff; scheduled/running/completed/canceled states; missing spreads, invalid pairs/prices/lines, multiple markets, explicit invalidation, and demo/provider separation. Use PostgreSQL for resolver integration.
  - Completion notes: Added app/strategies.py resolver. Frozen-clock tests cover before/at/after kickoff, source game states, absent kickoff, closed/inactive/invalid selections, paired teams/opposite lines, zero line and multiple markets. PostgreSQL preview tests verify canonical lookup and server-clock cutoff. Provider provenance integration remains unperformed because ingress is not implemented; demo provenance is null.

- [x] BE-04 — Implement the Random Strategy engine
  - Status: complete
  - Scope: Introduce typed candidate/BetDecision objects and an injectable random generator; generate decisions without persistence or execution side effects.
  - Dependencies: BE-03 supplies normalized candidates.
  - Acceptance criteria: Exactly one decision per eligible requested game using the uniform selection policy above; each decision belongs to its input candidates; copied line/price retain exact precision; empty candidates produce no decisions; both sides are reachable.
  - Validation: Deterministic injected-generator tests for candidate boundaries, both sides, multiple games, zero line, immutable copied values, and no input mutation. Avoid probabilistic pass/fail tests.
  - Completion notes: Added frozen BetDecision and typed ChoiceGenerator with SystemRandom default. Deterministic tests reach both sides, exercise empty/multiple candidate groups, stable sorting and immutable copied values without probabilistic assertions.

- [x] BE-05 — Expose decision preview and POST access
  - Status: complete
  - Scope: Connect strategy lookup, request validation, candidate resolver and engine to the preview endpoint; add typed OpenAPI responses and narrowly configured POST CORS.
  - Dependencies: BE-02–BE-04.
  - Acceptance criteria: Frontend receives decisions/skips with canonical IDs and exact values; unknown IDs fail before generation; inactive strategy is rejected; all-skipped case is explicit; no User/Strategy/Run/Bet writes during preview; no external requests; existing read and health/readiness routes remain compatible.
  - Validation: PostgreSQL API tests for success, mixed/all-skipped, malformed/duplicate/empty game IDs, missing entities, inactive strategy, database failure, decimal/timestamp serialization, and allowed/disallowed POST preflight. Assert preview causes no persistence changes.
  - Completion notes: Added four strategy endpoints in app/routes.py and typed schemas/OpenAPI; POST CORS enabled in main.py. PostgreSQL tests cover request errors, inactive strategy, mixed/all-skipped output, request order, exact decimal strings, all-ID validation before sampling and SELECT-only preview (four queries). Sanitized database failures and allowed/disallowed POST preflight pass.

- [x] BE-06 — Verify and document the slice handoff
  - Status: complete
  - Scope: Document migration/bootstrap and preview usage; validate complete backend behavior and hand off to frontend, recording available ingress integration honestly.
  - Dependencies: BE-02–BE-05. Frontend FE-04 performs the later UI validation; it does not block this backend-only delivery requested by CHIP.
  - Acceptance criteria: Backend checks pass on isolated PostgreSQL; documented local setup produces preview decisions; changing stored quotes does not mutate an already returned decision; no saved run/bet or realized profit is claimed.
  - Validation: Required backend regression suite, migration drift check, live demo API smoke test, and browser-origin API smoke test. The select/execute/render browser flow is validated in frontend FE-04 when UI implementation is requested. If ingress exists, verify its quote invalidation/provenance integration; otherwise record that unperformed integration and demo-only evidence.
  - Completion notes: README documents migration/bootstrap, four endpoints, payloads, eligibility, errors and integration limits. Full PostgreSQL suite: 64 passed; default suite: 51 passed/13 skipped. Live HTTP on 8003 returned four decisions/one unavailable-spread skip from five stored demo games with exact source parity; CORS/OpenAPI passed and Alembic check found no drift. Development migration 0002 and explicit baseline bootstrap applied; no Run/Bet tables. Slice 2 UI/browser-render validation stays with FE-04 under CHIP’s backend-only request.

## Epic acceptance and execution order

Both areas are complete: select games → execute Random Strategy → inspect decisions and skips. Decision values match eligible stored snapshots; server kickoff validation is authoritative; execution has no provider, wager, or accounting side effects. BE-02–BE-06 are complete. Frontend FE-01–FE-04 now validate the actual select/execute/render browser flow. Backend BE-06 is validated independently of that later UI work for CHIP’s requested backend-only delivery.

## Loop log

### 2026-10-01 — Slice 2 planning requested by CHIP

- Completed task IDs: None; planning only.
- Validation: Read repository instructions, design 1/3, ERD image, slice 1 plans, ingress plans, current models/schemas/routes/CORS setup and Games page/API client. Slice 1 completion evidence is prior evidence, not rerun here.
- Blockers: No blocker to delivering plans. Strategy ownership discrepancy requires resolution in BE-01 if applicable; ingress runtime/provenance remains separately unimplemented.
- Next steps: Start BE-01 when implementation is requested; align FE-01 to its finalized contract. All implementation tasks remain unchecked.

### 2026-10-01 — Planning behavior corrected by CHIP

- Completed task IDs: None; BE-01 retired without marking it complete.
- Changes: Removed deferred contract-finalization work; settled preview and candidate policy in the plan; preserved remaining IDs. AGENTS.md now requires implementation-ready plans and discussion with CHIP before planning delivery.
- Validation: Reviewed ownership wording in design 1 against the ERD; checked sibling links and remaining dependencies. No runtime changes.
- Blockers: Strategy ownership question raised directly with CHIP; this is a blocked draft until resolved. Earlier planning-delivery claims in the loop log are superseded by this entry.
- Next steps: Incorporate CHIP’s decision and authorized design clarification, finish both plans, then begin BE-02 when implementation is requested.

### 2026-10-01 — Shared strategies accepted by CHIP; planning finalized

- Completed task IDs: None; implementation remains not started.
- Changes: Referenced design/4_shared_strategies.html, recording CHIP’s decision that Strategies are universal with per-user custom strategies deferred. Removed active planning blockers and retained stable implementation IDs and historical loop entries.
- Validation: Governing design and sibling contracts agree on shared visibility and no Strategy ownership field; links and required task fields checked. No application changes or runtime tests.
- Blockers: None for planning. Earlier ownership-blocker entries are resolved by this decision.
- Next steps: BE-02/BE-03 for backend and FE-01 for frontend when implementation is requested.

### 2026-10-01 — Backend implemented in one execution loop

- Completed task IDs: BE-02, BE-03, BE-04, BE-05, BE-06. Backend area complete; entire epic awaits frontend FE-01–FE-04.
- Affected files: backend/app/models.py, schemas.py, routes.py, main.py, strategies.py, seed_strategy.py; migrations/versions/0002_create_strategies.py; backend/tests/test_strategies.py and test_migrations.py; README.md and both sibling plans.
- Validation: Locked uv-run PostgreSQL suite passed 64 tests using disposable databases; default suite passed 51 with 13 skipped. Migration upgrade/downgrade/re-upgrade and drift checks passed. git diff --check passed. Existing upstream Starlette/httpx deprecation warning remains.
- Live setup: Applied additive migration 0002 to development PostgreSQL and explicitly inserted baseline 40000000-0000-4000-8000-000000000001. Verification backend remains on http://127.0.0.1:8003 with docs at /docs; existing servers left untouched. HTTP strategy list/detail/preview, browser-origin CORS/preflight and OpenAPI passed; five games produced four exact-value decisions and one spread_unavailable skip. No provider calls, game edits, Run/Bet writes or development downgrade.
- Scope adjustment: CHIP requested backend-only delivery; BE-06 uses HTTP/browser-origin API evidence and leaves the full UI interaction to FE-04. Ingress has no runtime schema yet, so saved provider provenance/invalidation integration was not performed; do not claim live quotes.
- Blockers: None for backend completion.
- Next steps: FE-01 then remaining frontend tasks when requested. Backend endpoints are ready for integration.

### 2026-10-01 — Backend implementation request reverified

- Completed task IDs: BE-02–BE-06 remain complete. Inspected the existing working-tree implementation against governing designs 1, 3, and 4; no additional code changes were needed.
- Validation: `RUN_POSTGRES_TESTS=1 .venv/bin/python -m pytest --tb=short` passed all 64 tests, including disposable PostgreSQL migration cycle/drift, strategy persistence/bootstrap, API contracts, eligibility, and SELECT-only preview checks. Default suite passed 51 with 13 integration tests skipped. `git diff --check` passed.
- Environment: `uv` is unavailable on the current shell PATH, so checks used the existing Python 3.12 virtual environment. PostgreSQL access required sandbox escalation; the authorized rerun passed. One existing Starlette/httpx deprecation warning remains.
- Limitations: Prior live HTTP evidence above was not repeated; frontend rendering and provider ingress/provenance remain outside this backend-only request.
- Blockers: None for backend completion.
- Next steps: Frontend FE-01–FE-04 when requested.

### 2026-10-01 — Frontend implementation started

- Backend contract remains unchanged; frontend FE-01 is in progress under CHIP’s request.
- Next steps: Validate frontend integration against the existing decision preview endpoints.

### 2026-10-01 — Frontend browser handoff completed

- Frontend FE-01–FE-04 complete; backend contract unchanged. Demo slice epic is complete.
- Validation: Frontend build and 21 browser regressions passed; two live PostgreSQL-backed Chrome flows passed at desktop/mobile widths with exact stored selection parity. Backend no-write evidence remains applicable. Provider ingress/provenance integration remains separate and unperformed.
- Next steps: Later Dry Run slice and separate ingress work.
