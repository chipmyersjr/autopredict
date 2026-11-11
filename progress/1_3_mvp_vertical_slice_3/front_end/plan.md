# Design 1, part 3 — Dry Run Bets frontend

Area status: `complete`

Planning status: settled implementation contract; frontend implementation authorized October 2, 2026.

## Objective and governing design

Extend the existing Games/Random Strategy flow to create a user-owned Dry Run, display persisted theoretical Bets, and inspect Run history after reload.

- [MVP](../../../design/1_mvp.html), sections 5–6, 8–9 (vertical slice 3), and 11.
- [Canonical ERD](../../../design/2_mvp_erd.png), Runs, Bets and run_games.
- [Ingress](../../../design/3_game_info_ingress.html), sections 2 and 6–7: saved quote provenance, kickoff cutoff and retained history.
- [Shared strategies](../../../design/4_shared_strategies.html): shared strategies and User-owned Runs.
- [Completed slice 2 frontend](../../1_2_mvp_vertical_slice_2/front_end/plan.md).
- [Separate ingress frontend](../../3_1_game_info_ingress/front_end/plan.md).
- [Sibling backend plan and authoritative shared API contract](../backend/plan.md).

## Current implementation and settled scope

GamesPage supports game selection, shared Random Strategy discovery, decision previews and skips. Add a distinct `Create Dry Run` action using those selected games and strategy, with starting bankroll and fixed stake inputs. Preserve `Preview decisions`; label that creation generates fresh server decisions and records theoretical Bets. Do not submit preview decisions or choose bets in the browser.

Use starting defaults `1000.00` and `10.00`, editable positive money inputs with at most two decimal places. Preserve strings through submission; use exact cents for local checks. Backend eligibility and budget validation are authoritative. Do not introduce a wallet, settlement control, P&L chart, authentication or user selector.

Add simple Games/Runs navigation using hash routes (`#/games`, `#/runs`, `#/runs/<uuid>`), retaining Games as the default and supporting reload/back/forward without additional server routing requirements. Run detail displays its persisted Bets. Separate global Bet-history UI and dashboard metrics remain later work; this slice inspects Bets through their Run.

## API and interaction contract

- Follow the backend contract for `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/bets`, and `GET /api/bets/{id}`. Typed clients preserve UUIDs, decimal strings, nullable metrics/provenance and UTC timestamps. The detail screen uses Run and Run-bets reads; no separate Bet screen is required.
- Send strategy UUID, selected distinct game UUIDs, starting bankroll/stake strings, and optional name. No user_id or BetDecision input. Use the server-resolved local simulation User.
- Generate a UUID Idempotency-Key per submitted intent and save the pending key/body in sessionStorage before sending. Disable duplicate submission while in flight. On timeout/transport error or a lost response, retain the exact body/key and offer `Retry creation`; retry replays the same request. Restore unresolved creation after reload in the same tab. After success, clear the pending intent and navigate to the returned Run.
- A definite validation/conflict/configuration response allows correction; changing inputs starts a new key. With an ambiguous transport outcome, first offer same-key recovery; explicitly choosing to discard that pending intent explains that an earlier Run may already exist and links to history. Abort or navigation does not imply rollback. A stale completion cannot redirect a newer view or overwrite a newer submission.
- Show useful 404/409/422/503 errors, including inactive strategy, no eligible games, budget rejection, missing local User setup, key conflict, and unavailable database. Mixed eligibility succeeds and displays persisted per-game skips. No all-skipped Run is created.
- Run history shows name (fallback short ID), strategy, start time, status and Bet count. Detail shows starting bankroll, stake, committed stake, available bankroll, open Bet count, selected games and skip reasons. Nullable settlement metrics appear as `Not settled`, without fabricated zero profit or ending bankroll.
- Bet rows show snapshot matchup/team, signed/zero line, exact decimal price, stake, placement time, status and available saved quote provenance. Demo/null provenance is labeled as demo data; provider observations are saved prices. Render historical snapshots independently of current Selection/Game updates. Include a linkable Run ID and reload-safe empty/loading/error/retry/not-found states.
- Keep current Games order, demo labeling, local kickoff display and selection eligibility guidance. Server cutoff may produce skips even if the browser allowed selection. No creation/list/detail read triggers provider refresh. If ingress exists, retain its current-week Games/Refresh flow; historical Run detail remains readable outside that window.

## Tasks

- [x] FE-01 — Add typed Run/Bet clients and retry identity handling
  - Status: complete
  - Scope: Add Run/Bet request/read types and clients, Idempotency-Key support, safe error parsing, and session-persisted pending creation state using the settled backend contract.
  - Dependencies: Existing API infrastructure; backend BE-03 for live verification.
  - Acceptance criteria: Exact decimal strings/null values preserved; same-intent retries reuse key/body across reload; success clears pending state; malformed saved state is safely discarded; stale/aborted requests cannot overwrite current state.
  - Validation: Controlled API/browser tests for 201/200, errors, timeout/lost response, restored pending intent, key reuse and new-key creation after correction; verify POST preflight with the custom header when backend exists.
  - Completion notes: Added typed `frontend/src/api/runs.ts`, safe allowlisted error messages, positive money parsing in exact BigInt cents, strict sessionStorage intent validation, UUID request identity and custom-header creation. `DryRunForm.tsx` retains original body/key on unknown transport outcomes and reload, blocks duplicate requests, and clears completed/definite-failure intents. Controlled browser tests cover restore/replay, correction/new keys, malformed state and unavailable storage; live PostgreSQL browser tests verify real response-loss replay and successful custom-header preflight.

- [x] FE-02 — Add Dry Run creation to selected games
  - Status: complete
  - Scope: Add bankroll/stake/name inputs and distinct creation action; connect selected games/shared strategy, disabled/in-flight state, authoritative errors and ambiguous-outcome recovery.
  - Dependencies: FE-01; backend BE-03 for live creation.
  - Acceptance criteria: Accessible labeled money inputs accept valid cents; invalid input cannot submit; browser sends IDs/settings only; duplicate clicks cannot create multiple intents; preview remains usable; creation success opens saved Run and skipped games are visible; transport failure recovery uses the original intent.
  - Validation: Browser interactions covering defaults, edits, positive/precision limits, budget rejection, inactive strategy, kickoff skips, all-skipped failure, duplicate clicks, lost response/retry, selection changes and keyboard/mobile operation.
  - Completion notes: Implemented `frontend/src/components/DryRunForm.tsx` and Games integration with default exact decimal inputs, optional name, fresh UUID intents, in-flight protection, safe server errors, same-key recovery and explicit discard confirmation. Preview is labeled Preview decisions and remains independently usable. `runs.spec.ts` verifies invalid/overflow money, correction, server error reasons, actual 15-second timeout, lost-response reload/retry, unknown server outcomes, selection changes during creation, stale navigation, storage failure and keyboard operation. Live browser creation/recovery passed at 375px and 1280px.

- [x] FE-03 — Add Run history and immutable Bet inspection
  - Status: complete
  - Scope: Add hash navigation, Runs list and Run detail/Bets views, snapshot/provenance rendering, committed/available bankroll labels and unsettled states.
  - Dependencies: FE-01; backend BE-03 for live reads. Can proceed independently of FE-02.
  - Acceptance criteria: Reload/back/forward restores the intended Run; saved snapshots display even when current quotes or current-week Games differ; exact values and null outcome/metrics render honestly; no fresh decisions on reads; loading/empty/error/not-found recover; responsive keyboard-accessible views.
  - Validation: Controlled browser tests for navigation/reload, history ordering, skips, snapshot/current-data differences, zero/signed spreads, four-decimal prices, nullable metrics/provenance, malformed/unknown route IDs, stale reads, retry and mobile overflow.
  - Completion notes: Implemented hash navigation in `frontend/src/App.tsx`, history/Run detail in `frontend/src/pages/RunsPage.tsx`, shared exact spread formatting in `frontend/src/format.ts`, and responsive styles. Detail uses stored Run and Bet APIs, renders saved participants/line/price/stake/provenance, nullable outcomes and accounting honestly, and has retry/empty/loading/not-found states. Controlled tests cover reload/back/forward, stale detail reads, error retry, skips, signed/zero lines, four-decimal odds, demo/provider provenance and keyboard links. Actual PostgreSQL quote/game mutation leaves reloaded snapshot display unchanged; desktop/mobile screenshots inspected without overflow.

- [x] FE-04 — Validate and document the complete saved-run flow
  - Status: complete
  - Scope: Verify real Games → create → inspect → reload → history flow with dedicated PostgreSQL-backed demo data; document setup and test evidence.
  - Dependencies: FE-01–FE-03 and backend BE-03–BE-04.
  - Acceptance criteria: Persisted Run and Bet snapshots match server execution; same-key recovery returns one Run; reload retrieves the same Bets; changed current quotes do not alter historical values; earlier Games/preview regressions pass; no provider calls, settlement or realized P&L implied.
  - Validation: TypeScript/production build, relevant Playwright suite, live PostgreSQL-backed desktop/mobile smoke tests with exact snapshot parity and response-loss replay, keyboard use and screenshot inspection. Use dedicated data for quote mutation rather than editing existing development fixtures. Record ingress integration as unperformed if absent.
  - Completion notes: Added controlled `frontend/tests/runs.spec.ts`, actual PostgreSQL browser acceptance in `runs-live.spec.ts`, safe disposable backend helper in `tests/support/live_backend.py`, and setup/recovery/validation documentation in `README.md`. Production TypeScript/Vite build passes. Standard browser suite: 41 passed, 5 live tests skipped; dedicated live earlier Games/preview run: 12 passed; saved-run mobile/desktop live run: 2 passed. Real committed-response loss/replay, single persisted Run, exact API/selection parity and post-mutation reload/history parity verified. Creation/detail screenshots at 375px and 1280px visually inspected and no horizontal overflow observed. Backend regression: 88 passed, including migration drift/cycle. Test server/database cleanup verified. Development fixtures were untouched; ingress/provider integration is unperformed because ingress is absent.

## Epic acceptance and execution order

FE-01 → FE-02/FE-03 → FE-04. Backend owns validation, randomness, transactionality and persistence; frontend owns input, retry identity and historical presentation. Both sibling plans must complete their tasks before slice 3 is complete.

## Loop log

### 2026-10-01 — Slice 3 planning

- Completed task IDs: None; all implementation tasks remain not_started.
- Validation: Reviewed governing design, completed slice 2 UI/client and sibling backend contract. Aligned endpoints, exact decimals, local ownership, skip/budget semantics, request replay and unsettled labels. Runtime tests are not applicable to this planning-only change.
- Blockers: None for planning. Live creation/read verification depends on backend BE-03; provider integration remains in the separate ingress epic.
- Next steps: FE-01 when implementation is requested, then creation/history work and FE-04 validation.

### 2026-10-02 — Backend handoff

- Completed frontend task IDs: None; frontend implementation remains outside this request.
- Backend BE-01–BE-03 complete; the documented settled contract is implemented with exact decimal strings, nullable provenance/outcomes, saved ordered skips and UUID Idempotency-Key replay. No shared contract changes were needed.
- Validation: Backend PostgreSQL regressions, OpenAPI, custom-header CORS and actual HTTP create/replay/history/Bet smoke pass. Full browser acceptance remains unperformed.
- Blockers: Frontend FE-01–FE-03 must be implemented before FE-04 and backend BE-04 can close.
- Next steps: FE-01 against the live backend contract, followed by FE-02/FE-03 and FE-04.

### 2026-10-02 — Frontend implementation and complete slice acceptance

- Completed task IDs: FE-01, FE-02, FE-03, FE-04; sibling backend BE-04 acceptance dependency satisfied. Both areas are complete.
- Implementation: Typed exact-value clients; tab-persisted creation identity; distinct Preview decisions/Create Dry Run controls; positive money/name inputs; safe definite errors versus unknown-outcome recovery; explicit pending discard; Games/Runs/Run hash routes; saved snapshot/provenance/skip/accounting display.
- Validation: `npm run build` passed. `TEST_FRONTEND_PORT=5187 npm test` passed 41 controlled tests; five live tests skipped in that command. Against a generated disposable PostgreSQL server on 8017, `LIVE_API=1 TEST_API_BASE_URL=http://127.0.0.1:8017 TEST_FRONTEND_PORT=5188 npm test -- games.spec strategies-live` passed 12, and `LIVE_RUN_DB_FILE=/private/tmp/autopredict-slice3-browser.json TEST_API_BASE_URL=http://127.0.0.1:8017 TEST_FRONTEND_PORT=5188 npm test -- runs-live` passed two mobile/desktop flows. Backend `RUN_POSTGRES_TESTS=1 .venv/bin/pytest -q --tb=short` passed 88. `git diff --check` passed.
- Evidence: Live committed response intentionally lost; original key/body restored after reload and replayed with 200; exactly one Run in history. Bets match stored Selection line/price and fixed stake. Dedicated games/quotes changed after creation; Run detail and API Bets remained identical after reload. Keyboard creation/navigation, 15-second timeout recovery, stale navigation/reads, exact nullable metrics, mobile width and safe errors covered. Ignored screenshots `frontend/test-results/runs-create-live-{375,1280}.png` and `runs-live-{375,1280}.png` inspected.
- Cleanup: Disposable server stopped, generated database dropped and metadata removed. No development schema/fixture changes. Existing upstream backend deprecation and Node color-environment warnings are non-failing.
- Blockers: None for this slice. Provider integration remains explicitly unperformed because the independent ingress epic is absent.
- Next steps: No slice 3 tasks remain. Settlement/P&L and ingress continue under their own governing plans.
