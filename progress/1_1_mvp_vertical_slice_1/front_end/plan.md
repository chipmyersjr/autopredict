# Design 1, part 1 — Games and spreads frontend

Area status: `not_started`

## Objective and governing design

Replace the initialization placeholder with a working React Games page that reads persisted college football games and displays their spread selections. Complete the frontend portion of vertical slice one against the completed backend; the epic is complete only when both sibling plans meet their acceptance criteria.

Sources of truth:

- [MVP proposal](../../../design/1_mvp.html), sections 3–4 (Game → Market → Selection and seeded data), 6 (read APIs), 7 (React/TypeScript/Vite), 8 (Games view), 9 (vertical slice one), and 11 (browser display).
- [MVP ERD](../../../design/2_mvp_erd.png) for domain relationships and nullable fields.
- [Ingress design](../../../design/3_game_info_ingress.html), sections 6–7: keep demo data clearly labeled. Provider refresh, current-week filtering, quote provenance and server kickoff eligibility are implemented in the [separate ingress frontend plan](../../3_1_game_info_ingress/front_end/plan.md); this slice supplies its prerequisite Games view.
- [Backend plan](../backend/plan.md): BE-01–BE-06 are complete, including nested read responses and development CORS.

## Current implementation and integration contract

- `frontend/src/pages/GamesPage.tsx` renders only the initialization heading. `src/main.tsx` already mounts it with React StrictMode; existing CSS supplies a minimal page container. Reuse this application rather than add a second entry point.
- Backend `app/routes.py` and `app/schemas.py` implement `GET /api/games`: an unfiltered array, ordered by kickoff then UUID, with nested markets and selections. One request supplies the page; no per-game requests are needed.
- Consume game IDs, teams, season/week, kickoff, stored status, nullable scores/venue/notes, and nested market/selection fields. Spread lines and decimal odds are exact JSON strings; line can be null. Keep the raw values as strings and distinguish zero (pick’em) from missing line.
- Display kickoff in the browser's local timezone with a visible timezone label. Preserve stored game status; elapsed time alone does not establish completion. Unfiltered records can include historical or inactive data, so do not call the entire list “upcoming” or promise live availability.
- Display spread selections from `type = spread`, `status = active` markets and `is_active = true` selections with a non-null line. Associate each line/price with its selection's team name. Never construct a missing opposing selection or merge selections across markets; render multiple markets separately when present.
- Label this seeded-data view as fictional demo games and odds, not current schedules or live bookmaker prices. Do not expose arbitrary notes as a replacement for that label.
- Make the API base URL configurable with a public Vite environment variable, e.g. `VITE_API_BASE_URL`. The prior backend verification used `http://127.0.0.1:8001`; confirm availability at implementation time rather than assume that process remains running. Document the normal default and the port override.
- Backend CORS allows `http://127.0.0.1:5173` and `http://localhost:5173`. Alternate frontend ports require adding their origins to the root `CORS_ORIGINS` JSON array and restarting the backend. No provider credentials belong in frontend configuration.

## Reviewable tasks

- [ ] FE-01 — Connect the Games page to the read API
  - Status: `not_started`
  - Scope: Add TypeScript response types and a small games API client, configurable API base URL, and page request state using the existing React/Vite setup. Load `GET /api/games` on mount; handle non-2xx responses and transport failures. Clean up requests on unmount and prevent stale responses from replacing newer state, including StrictMode effect cleanup.
  - Dependencies: Completed backend BE-03 and BE-05; existing frontend bootstrap.
  - Acceptance criteria: The page obtains the nested games array from the configured backend without per-game calls, provider calls, or embedded fixture fallback. Decimal strings/nulls reach the view unchanged. Loading, success, empty, and failure states are distinguishable; failed requests do not leave permanent loading state.
  - Validation: Frontend request/state tests with controlled responses cover nested success, empty array, HTTP 503, network failure and aborted/stale requests. Run `npm run build` from `frontend/` with its declared Node 24 runtime.
  - Completion notes: Pending. Expected files: frontend API/types modules, GamesPage.tsx, Vite environment declarations/example and package scripts/dependencies only as required for meaningful frontend tests.

- [ ] FE-02 — Render games and spread selections
  - Status: `not_started`
  - Scope: Replace the placeholder with a Games heading, explicit demo-data label and a readable list or table. Show away/home teams, local kickoff with timezone, season/week and stored status; show available scores without converting null to zero. Render spread markets with each team's signed handicap and labeled decimal odds. Retain backend game order.
  - Dependencies: FE-01.
  - Acceptance criteria: Seeded API data shows five games, four spread markets and eight selections when using the documented untouched seed. Positive/negative lines retain their sign; zero is displayed as pick’em; exact odds remain readable. A game without markets remains visible with “Spread unavailable.” Closed markets and inactive/null-line selections are not presented as available spreads. Multiple markets retain their ownership and any incomplete market does not acquire fabricated selections. The view does not imply that demo quotes are live or actionable bets.
  - Validation: Rendering/formatting tests cover paired lines, zero versus null, exact odds, inactive selections, closed markets, multiple/incomplete markets, nullable/zero scores and local-time formatting. Compare the page's values with a controlled nested response.
  - Completion notes: Pending. Expected files: GamesPage.tsx, small display components/formatters if useful, and relevant tests.

- [ ] FE-03 — Finish page states and responsive accessibility
  - Status: `not_started`
  - Scope: Style the games view in the existing stylesheet; provide readable loading, no-games and request-error messages, plus a keyboard-accessible Retry action for failed stored-data reads. Make long team names and spread content work on small screens. Use semantic headings/list or table markup and accessible status/error announcements.
  - Dependencies: FE-01, FE-02.
  - Acceptance criteria: Users can distinguish an empty database from a failed request and from a game without spreads. Retry reissues only the stored games read and recovers after failure. Loading prevents repeated retry requests. At mobile and desktop sizes the content is readable without clipped teams/odds; controls have visible focus and messages do not rely solely on color.
  - Validation: Interaction tests cover error → Retry → success and loading behavior. Browser checks at approximately 375px and 1280px verify layout, keyboard focus and state messages; record evidence rather than mark visual checks complete from a build alone.
  - Completion notes: Pending. Expected files: GamesPage.tsx, styles.css and page interaction tests.

- [ ] FE-04 — Verify and document the complete games slice
  - Status: `not_started`
  - Scope: Document frontend environment/start commands alongside existing backend migration/seed instructions in README. Validate the real PostgreSQL → FastAPI → browser flow, run frontend checks, and record completion evidence in both sibling plans without reopening completed backend tasks unless a defect requires it.
  - Dependencies: FE-01–FE-03; completed backend BE-02–BE-06 and a running migrated/seeded development database/API.
  - Acceptance criteria: Following the documented setup opens the Games page with persisted demo games and correct spreads. Browser network access/CORS works for the documented origins and configurable backend port. Loading, empty, unavailable spreads and failure/recovery have validation evidence. All applicable frontend tasks and slice acceptance criteria are satisfied before marking the area complete.
  - Validation: Run frontend tests and `npm run build` on Node 24; browser smoke test against the actual seeded backend and compare displayed values to `/api/games`, including the zero-line pair and game without markets. Use controlled responses or an isolated test database for empty/error cases; do not delete or reseed CHIP's data for validation. Run `git diff --check`; record actual results and any unperformed checks.
  - Completion notes: Pending. Expected files: README and both sibling plans; no design edits.

## Frontend acceptance criteria

- Opening the existing UI displays API-backed college football games and spread selections instead of the initialization heading.
- Team ownership, signed/zero lines, exact decimal odds, local kickoff times, stored statuses and nullable scores are represented correctly.
- Demo data is clearly distinguished from current schedules and live odds.
- Loading, no games, unavailable spreads, request failure and retry recovery are clear and verified.
- The page is readable on mobile/desktop and operable by keyboard.
- Frontend tests/build and an actual seeded-backend browser smoke test pass, with setup and evidence recorded.
- Provider Refresh/current-week behavior remains tracked in the ingress epic; strategy execution, bets, settlement and P&L remain later MVP slices.

## Loop log

### 2026-09-30 — Backend planning handoff

- Completed task IDs: None.
- Validation: Reviewed governing design and backend proposed contract; no UI implementation or checks performed.
- Blockers: None for planning; implementation needs the backend contract available.
- Next step: Plan frontend tasks when requested. The full epic remains incomplete until both areas meet slice acceptance criteria.

### 2026-09-30 — BE-01 implementation handoff

- Backend completed BE-01 persistence and explicit migrations under the MVP proposal and ERD; API implementation remains pending BE-03/BE-04.
- Validation: All 8 backend tests passed, including PostgreSQL schema/constraint and migration-cycle tests. No UI checks were needed.
- Frontend scope and proposed response contract are unchanged; no frontend implementation is required for BE-01.
- Next step: Backend BE-02; frontend planning remains deferred until requested.

### 2026-09-30 — Progress directory numbering

- Adopted design-number/part-number naming; moved this existing plan without changing task IDs, statuses, or completed work.
- Validation: Sibling plans and governing design links resolve after rename.
- Next: Continue the existing task sequence.

### 2026-10-01 — Backend slice execution

- Scope: Backend BE-02–BE-06 implement the documented unfiltered read contract and demo fixtures under design 1/2; design 3 provider refresh and current-week filtering remain separate work.
- Frontend implementation is deferred; this loop provides a testable JSON URL and OpenAPI documentation.
- No change to decimal-string/UTC contracts; frontend CORS configuration will be documented after validation.

### 2026-10-01 — Completed backend handoff

- Completed backend IDs: BE-02–BE-06. All four read APIs and their Pydantic/OpenAPI contracts are available. Backend area is complete; frontend remains `not_started` with implementation tasks deferred until requested.
- Live review URLs: `http://127.0.0.1:8001/api/games` (5 demo games, 4 markets, 8 selections) and `http://127.0.0.1:8001/docs`. Server left running for CHIP; GamesPage.tsx remains the initialization placeholder.
- Validation: 33 backend tests passed, including isolated PostgreSQL seeding/API/migration checks, CORS, exact decimal strings and UTC, and fixed query counts. Live data matched its snapshot after ordinary PostgreSQL restart. No UI validation performed in this backend-only scope.
- Contract: Consumers retain raw Decimal strings, distinguish zero from null, show fictional demo labeling, and handle games without markets. Unfiltered reads retain stored historical/inactive states; design 3 current-window filtering and kickoff availability remain in the separate ingress epic.
- Blockers: None for frontend planning. Next step: Plan/implement frontend against the available API when requested. The full vertical slice remains incomplete until frontend acceptance criteria are met.

### 2026-10-01 — Frontend implementation planning requested by CHIP

- Completed task IDs: None; planning only. Area remains `not_started` because no UI implementation or runtime validation was performed.
- Replaced the handoff-only body with FE-01–FE-04, dependencies, acceptance criteria, validation and slice completion criteria. Earlier loop entries above are retained as historical backend handoffs; their planning deferral no longer applies.
- Validation: Reviewed AGENTS.md, design 1/3, both slice plans, ingress frontend plan, backend routes/schemas, and current frontend entry point/page/styles/package/Vite configuration. Confirmed the Games page is still a placeholder and the backend supplies the required nested read contract. Prior backend results are referenced, not rerun or claimed as new validation.
- Blockers: None for implementation planning. Confirm local API availability when starting runtime work.
- Next step: FE-01, then FE-02, FE-03 and FE-04 in dependency order. Keep the backend area complete and the full epic incomplete until frontend validation passes.
