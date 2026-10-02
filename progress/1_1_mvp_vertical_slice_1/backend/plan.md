# Design 1, part 1 — Games and spreads backend

Area status: `complete`

## Objective and governing design

Persist realistic demo college football games and spread selections in PostgreSQL and expose them through FastAPI so the Games page can replace its placeholder with actual API data.

Sources of truth:

- [MVP proposal](../../../design/1_mvp.html), sections 2–4 (scope, domain, data), 6 (endpoints), 7 (stack), 9 (slice 1), and 11 (success criteria).
- [MVP ERD](../../../design/2_mvp_erd.png), specifically games, markets, selections, their relationships, types, and timestamps.
- [Ingress design](../../../design/3_game_info_ingress.html), section 6: demo fixtures remain separate and clearly labeled; provider refresh/current-window work stays in design 3 part 1.
- [Completed initialization plan](../../0_init_apps/backend/plan.md) for the existing setup.

BE-01 through BE-06 are complete and validated. The backend can be completed independently, but the full vertical slice is complete only when the frontend also displays games and spreads.

## Scope and implementation decisions

- Reuse existing FastAPI, PostgreSQL, SQLAlchemy, settings, and health/readiness behavior.
- Implement only Game, Market, and Selection. Users, strategies, runs, bets, settlement, provider integrations, write APIs, and other market types belong to later work.
- Introduce Alembic with root `migrations/` as shown in the design; keep configuration in `backend/alembic.ini` so documented commands run from `backend/`.
- Configure migrations from the same root `.env` and SQLAlchemy metadata as the app. Migrations are explicit commands, never automatic on server startup. Do not use `create_all` as a substitute.
- Use synchronous request-scoped SQLAlchemy sessions backed by the existing application engine; close sessions on every request and roll back failed transactions.
- Use UUID primary/foreign keys, timezone-aware PostgreSQL timestamps stored in UTC, and exact numeric types from the ERD. Preserve nullable scores and selection lines; require a line for the spread records created by the seed loader.
- Use the ERD's lowercase status vocabulary: game `scheduled`, `in_progress`, `completed`, `canceled`; market `active`, `closed`, `settled`. Represent spread type as `spread`; no other market types are implemented.
- Local pricing convention for this slice: decimal odds, greater than 1, represented as exact decimal strings in JSON. The ERD allows decimal odds or implied probability; choosing decimal odds here makes sample data unambiguous. This does not finalize later bet accounting.
- Seed fictional matchups with real college team names and realistic spreads, explicitly labeled demo data. Do not claim current schedules or live bookmaker prices.
- Provide an explicit seed command, proposed `uv run python -m app.seed --anchor-date YYYY-MM-DD`; omitted date defaults to the current UTC date. Schedule demo games relative to that anchor. Stable fixture UUIDs make repeat seeding idempotent; existing records are not overwritten or deleted. Changing the anchor does not silently reschedule existing fixtures.
- Demo set: at least four scheduled games, each with one active spread market and two active team selections with opposite lines; include a pick'em line of zero. Add one game with no markets to exercise missing-spread display. Scores are null for scheduled games.
- No live provider or generalized ingestion framework is needed. Keep seed loading separate from API handlers so provider ingestion can be introduced later.
- Eager-load relationships for list responses to avoid queries per game. List endpoints return all stored rows in stable order for the bounded demo dataset; filtering and pagination are deferred.

## Persistence contract

Implement ERD fields for the three tables, including optional metadata:

| Table | Fields |
| --- | --- |
| `games` | id, season, week, home_team, away_team, start_time, status, home_score, away_score, venue, notes, created_at, updated_at |
| `markets` | id, game_id, type, status, description, created_at, updated_at |
| `selections` | id, market_id, side, line, price, is_active, notes, created_at, updated_at |

Foreign keys enforce Game → Market → Selection ownership. Index child foreign keys and game start time. Keep descriptive text optional where the design does not require it. Enforce nonnegative scores when present. Do not impose a one-market-per-game uniqueness rule: the design allows multiple markets.

For these spread selections, `side` contains the team's name matching `home_team` or `away_team`. The selection's signed line determines its displayed handicap; it is not stored on Game or Market. Seed validation checks paired teams, opposite lines, and valid decimal prices before committing one transaction.

## Proposed read API contract

These response details fill in the design's endpoint contract for this slice; they do not supersede design requirements. Use Pydantic schemas and expose them in `/docs`.

| Endpoint | Success |
| --- | --- |
| `GET /api/games` | 200, array of Game objects with nested `markets`, each including `selections` |
| `GET /api/games/{game_id}` | 200, one Game object with the same nested shape |
| `GET /api/games/{game_id}/markets` | 200, array of Market objects including selections |
| `GET /api/markets/{market_id}` | 200, one Market object including selections |

- Game responses include all Game fields listed above; Market and Selection responses include their corresponding fields.
- UUIDs are JSON strings; timestamps are ISO 8601 with UTC offset; `line` and `price` are decimal strings (or null for nullable line). JSON booleans are used for `is_active`.
- Game ordering: `start_time`, then id. Nested markets and selections: stable ordering by id.
- Return stored statuses and inactive records; consumers distinguish available selections by market status and `is_active`. Do not silently remove completed or historical rows.
- Empty database: `/api/games` returns `[]`. Existing game without markets: markets endpoint and nested markets return `[]`.
- Unknown valid UUID: 404 with `{"detail":"Game not found"}` or `{"detail":"Market not found"}`. Malformed UUID: FastAPI validation response, HTTP 422.
- Database unavailable: data endpoints return HTTP 503 with a generic detail; no credentials or raw driver exception in responses. Preserve `/api/health` and `/api/ready` contracts.

Example nested market, within a Game whose home team is USC and away team is UCLA:

```json
{
  "id": "10000000-0000-4000-8000-000000000001",
  "game_id": "20000000-0000-4000-8000-000000000001",
  "type": "spread",
  "status": "active",
  "description": "Demo spread market",
  "created_at": "2026-09-30T00:00:00Z",
  "updated_at": "2026-09-30T00:00:00Z",
  "selections": [
    {
      "id": "30000000-0000-4000-8000-000000000001",
      "market_id": "10000000-0000-4000-8000-000000000001",
      "side": "USC",
      "line": "-3.50",
      "price": "1.9091",
      "is_active": true,
      "notes": "Demo data",
      "created_at": "2026-09-30T00:00:00Z",
      "updated_at": "2026-09-30T00:00:00Z"
    }
  ]
}
```

The example shows one selection for brevity; seeded spread markets contain both team selections.

## Reviewable tasks

- [x] BE-01 — Add domain persistence and migrations
  - Status: `complete`
  - Scope: Add SQLAlchemy models/metadata for the three tables, relationships, ERD types, constraints/indexes, Alembic dependency/configuration, and initial migration.
  - Dependencies: Completed epic 0 backend setup.
  - Acceptance criteria: `uv run alembic upgrade head` from `backend/` creates the three tables in PostgreSQL with correct keys/types; no unrelated domain tables; migration tooling shares environment settings. App startup does not create schema.
  - Validation: Run upgrade on a dedicated empty test database; inspect schema and reject orphan child rows/negative scores; exercise downgrade and re-upgrade only on that disposable database. Never downgrade the user's development database as a test.
  - Completion notes: Added `backend/app/models.py`, Alembic dependency and lockfile, `backend/alembic.ini`, root migration environment/template and revision `0001`, `backend/tests/test_migrations.py`, and README migration/testing commands. PostgreSQL 17 validation passed: explicit uv-run upgrade on a dedicated empty database; two integration tests on randomly named disposable databases cover keys/types/indexes, orphan rejection, negative scores/status/type/price constraints, decimal precision, nulls, relationships, ORM timestamps, Alembic metadata comparison, downgrade and re-upgrade. Full suite: 8 passed, one existing upstream test-client deprecation warning. No startup schema creation or development database migration. Temporary test databases removed.

- [x] BE-02 — Load reproducible demo games and spreads
  - Status: `complete`
  - Scope: Implement validated demo fixtures and explicit transactional seed command with anchor-date option and stable IDs.
  - Dependencies: BE-01.
  - Acceptance criteria: At least five games as described above; spread market pairs have correct signs, team names, exact odds, and UTC dates. Running twice creates no duplicates and does not overwrite existing records. No seeding on app startup.
  - Validation: Seed dedicated PostgreSQL test database twice; verify counts and relationships; verify existing-record preservation, zero-line pair, and rollback on invalid fixture data.
  - Completion notes: Added app/seed.py with deterministic UUIDs, UTC anchor-date fixtures, Decimal pair validation, and atomic PostgreSQL inserts that preserve existing fixture graphs. tests/test_seed.py: 7 passed, including dedicated database repeat seed, edited-record preservation/different anchor, zero line, invalid fixtures, and rollback after a late database error. Shared disposable database fixture moved to tests/conftest.py.

- [x] BE-03 — Add games read endpoints
  - Status: `complete`
  - Scope: Add request-scoped session dependency, response schemas, game queries and router, nested serialization, and generic database-error handling.
  - Dependencies: BE-01; BE-02 supplies smoke-test data.
  - Acceptance criteria: Both games endpoints match the contract, show selections without extra frontend requests, handle empty database/missing UUID/invalid UUID, preserve decimal precision and UTC timestamps, and release sessions on success/failure.
  - Validation: API tests against dedicated PostgreSQL exercise nesting, ordering, null scores, no-market game, empty data, 404/422, and session cleanup. Simulated database failure returns sanitized 503; health/readiness regression tests pass.
  - Completion notes: Added app/routes.py games routes, app/schemas.py nested read schemas, and app/database.py request-scoped sessions. PostgreSQL API tests passed for empty/nested data, UTC timestamps and decimal strings, stable ordering, 404/422, and session release; sanitized 503 checks verify rollback/cleanup. List retrieval uses 3 SELECTs for both 5 and 25 games.

- [x] BE-04 — Add markets read endpoints
  - Status: `complete`
  - Scope: Implement game-market listing and market detail using the same session and response schemas.
  - Dependencies: BE-03.
  - Acceptance criteria: Both market endpoints return selections and consistent IDs/values; distinguish unknown game (404) from known game with no markets (200/[]); malformed IDs return 422; generic database failure returns 503.
  - Validation: PostgreSQL API tests cover happy paths, inactive selections, closed markets, zero line, missing entities, empty collection, and shared shapes with nested games responses.
  - Completion notes: Added both market routes using shared schemas/session dependency. All 10 tests/test_games_api.py checks passed, including response parity, known empty game versus unknown game, inactive/closed records, null/zero lines, missing/malformed IDs, and sanitized database failures.

- [x] BE-05 — Enable local frontend access
  - Status: `complete`
  - Scope: Add narrowly configured development CORS origins for `http://127.0.0.1:5173` and `http://localhost:5173`, configurable through root environment settings. Update `.env.example`; share API shape and decimal handling with the sibling frontend plan.
  - Dependencies: BE-03, BE-04.
  - Acceptance criteria: Browser frontend can read the API on a different port; allowed origins receive the correct CORS headers; unspecified origins receive no permission header; no wildcard credentials policy.
  - Validation: Test allowed/disallowed origins and preflight. Record how alternate Vite ports can be configured.
  - Completion notes: Added explicit CORS_ORIGINS JSON-list settings and origin validation, GET-only noncredentialed CORS middleware, and .env.example. All 8 tests/test_cors.py checks passed for both default origins, allowed/disallowed preflight, file/environment configuration overrides, and rejection of wildcard/path/credential origins. Alternate Vite ports can be added to CORS_ORIGINS and applied by restarting the backend.

- [x] BE-06 — Document and verify the backend slice
  - Status: `complete`
  - Scope: Document migration/seed commands, demo-data labeling, anchor-date semantics, four endpoints, example requests, isolated PostgreSQL test setup, and frontend contract in README. Run full backend checks and live seeded API smoke tests.
  - Dependencies: BE-02 through BE-05.
  - Acceptance criteria: Documented setup yields persisted games and spreads visible through all four APIs and `/docs`; tests exercise PostgreSQL rather than substituting SQLite. Existing initialization endpoints still work. Test data does not modify the user's database.
  - Validation: Follow setup commands, run backend tests and live API requests; verify persistence across an ordinary database restart; record exact checks/results and any unperformed validation. Inspect list-query behavior to confirm it does not scale one query per game.
  - Completion notes: README documents migrations, seed/anchor preservation, five demo fixtures, exact values, all four read routes/examples, CORS overrides, and isolated PostgreSQL tests. Full locked uv-run suite: 33 passed; default no-database suite: 23 passed/10 skipped. Local migration/explicit seed inserted 5 games, 4 markets, 8 selections. All four live routes, health/readiness/docs, and CORS passed on port 8001. An ordinary PostgreSQL container restart preserved the entire JSON snapshot exactly. Dedicated test DBs were dropped; local demo data remains for CHIP. Existing upstream Starlette/httpx warning remains. Port 8000 was already occupied and unresponsive; left untouched, launched verification server on 8001.

## Backend acceptance criteria

- PostgreSQL stores Game → Market → Selection through an explicit Alembic migration.
- Demo games/spreads load reproducibly and are clearly distinguished from live data.
- The four design endpoints return documented, consistent data and errors.
- The frontend can obtain games and paired spread selections in one request.
- UTC times, exact numeric values, empty data, missing entities, and unavailable database cases are handled.
- Relevant PostgreSQL integration/API tests and existing health/readiness tests pass.
- Local setup and frontend handoff are documented.

## Loop log

### 2026-09-30 — Backend planning

- Completed task IDs: None; planning only.
- Validation: Read AGENTS.md, MVP proposal, ERD, completed initialization plan, and current backend modules/dependencies. No runtime checks or implementation performed.
- Blockers: None for this seeded-data scope. No real data provider selected or required.
- Next step: BE-01 — Models and Alembic migration, then BE-02 — Seed data.
- Frontend: Maintain a handoff note in the sibling plan; full frontend task planning is deferred until requested.

### 2026-09-30 — BE-01 implementation

- Completed task IDs: BE-01.
- Validation: `uv run alembic upgrade head` from backend succeeded on dedicated empty PostgreSQL 17 database; `RUN_POSTGRES_TESTS=1 .venv/bin/pytest` passed all 8 tests. Alembic check found no drift before/after downgrade and re-upgrade. Integration fixtures create and remove their own databases. `git diff --check` passed.
- Blockers: None. Existing upstream Starlette/httpx deprecation warning remains. uv used from temporary installation as in epic 0; Docker/PostgreSQL access required sandbox approval.
- Next step: BE-02 — Reproducible demo seed command. Other backend tasks and the full vertical slice remain incomplete.
- Frontend: Persistence is available; API tasks remain pending and the proposed handoff contract is unchanged.

### 2026-09-30 — Progress directory numbering

- Adopted design-number/part-number naming; moved this existing plan without changing task IDs, statuses, or completed work.
- Validation: Sibling plans and governing design links resolve after rename.
- Next: Continue the existing task sequence.

### 2026-10-01 — BE-02 through BE-06 implementation

- Completed task IDs: BE-02, BE-03, BE-04, BE-05, BE-06. Backend area complete; full vertical slice awaits frontend work.
- Affected files: `backend/app/seed.py`, `schemas.py`, `routes.py`, `database.py`, `main.py`, `settings.py`; `backend/tests/conftest.py`, `test_seed.py`, `test_games_api.py`, `test_cors.py`, migration-test fixture refactor; root `.env.example`, README and both sibling plans.
- Validation: Full `RUN_POSTGRES_TESTS=1 uv run --locked pytest` from backend passed 33 checks using PostgreSQL disposable databases, including preserved seed edits/dates and atomic rollback, nested contracts and 404/422/503 handling, session cleanup, UTC/Decimal serialization, statuses/nulls/zero, CORS and migration regressions. Default suite passed 23 with 10 PostgreSQL checks skipped. List query counts were 3 SELECTs with both 5 and 25 games. `git diff --check` passed.
- Local review: `uv run --locked alembic upgrade head` and `uv run --locked python -m app.seed --anchor-date 2026-10-01` succeeded on local development PostgreSQL. All four read routes and health/readiness/docs/CORS passed against `http://127.0.0.1:8001`. Five games/four markets/eight selections matched an exact pre-restart JSON snapshot after `docker compose restart db` and health recovery. No development downgrade, data deletion, or provider calls.
- Runtime: API verification server left running on port 8001 for CHIP; existing server on 8000 left untouched because it did not respond to the initial probe. uv used from `/private/tmp/autopredict-uv-tools/bin/uv` because it remains absent from PATH. Sandbox-approved PostgreSQL/server access used. One existing upstream test-client warning remains.
- Governing design: Read design 1/2 and subsequent design 3. This slice implements demo/unfiltered reads; provider refresh, provenance and current-week/kickoff eligibility additions remain in `3_1_game_info_ingress`. Demo data is labeled and has distinct stable UUIDs.
- Blockers: None for backend completion.
- Next steps: Implement Games-page frontend tasks when requested, or continue the separately planned ingress epic. Frontend remains `not_started`; backend completion does not mark the full product slice complete.

### 2026-10-01 — Frontend plan aligned for implementation

- Completed task IDs: None in this planning loop; BE-01–BE-06 remain complete.
- Replaced the sibling frontend handoff-only body with FE-01–FE-04 for API loading, games/spread rendering, page states/accessibility, and end-to-end validation. Earlier frontend planning deferral entries are historical; the actionable sibling plan now governs execution.
- Validation: Reviewed existing routes/schemas and frontend placeholder against design 1 and design 3. No API contract changes or new runtime checks in this loop.
- Blockers: None for frontend planning. Next step: Frontend FE-01; record final slice integration evidence after FE-04. Full epic remains incomplete.
