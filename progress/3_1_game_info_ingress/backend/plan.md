# Design 3, part 1 — Game ingress strategy proposal

Area status: `not_started`

## Objective and governing design

Research actual college-football sources and draft an ingress strategy consistent with `design/1_mvp.html` sections 2–5 and the existing Game → Market → Selection schema. The current proposal is in `design/3_game_info_ingress.html`. This plan includes completed design exploration and the now-requested backend implementation plan. This turn authorizes planning only; runtime tasks below remain not_started.

## Tasks

- [x] BE-01 — Research and draft ingress proposal
  - Status: complete
  - Scope: Compare sources, recommend a starting approach, specify normalization, identity, polling, recovery, freshness, and validation; preserve unresolved product choices.
  - Dependencies: None.
  - Acceptance criteria: Reviewable HTML proposal with primary-source links and explicit separation of recommendations from confirmed requirements.
  - Validation: Read governing design/current models; verify provider claims in current official documentation; check HTML structure and local links.
  - Completion notes: Initial research informed design/3_game_info_ingress.html; official-source comparisons and ingestion recommendations were reviewed. HTML structure and local links validated. The duplicate progress-area draft was subsequently removed at CHIP's request; consult the governing design document.
- [x] BE-02 — Publish requested design update
  - Status: complete
  - Scope: Transfer reviewed proposal to requested design file.
  - Dependencies: BE-01; CHIP's clarification of the explicit design-edit prohibition in AGENTS.md.
  - Acceptance criteria: Requested file contains proposal with permission resolved.
  - Validation: Inspect destination and diff.
  - Completion notes: CHIP explicitly authorized updating the target file and requested that AGENTS.md allow design edits during authorized collaboration.

## Loop log

## Current revision task

- [x] BE-03 — Revise proposal for free, on-demand weekly refresh
  - Status: complete
  - Scope: Keep CFBD and The Odds API only; incorporate CHIP's upcoming/FBS focus, manual Refresh button, Monday–Sunday window, automatic book selection, and informative quota handling.
  - Dependencies: BE-02; CHIP's explicit feedback and design-edit authorization.
  - Acceptance criteria: Remove superseded sources, paid-path suggestions, scheduled polling, and 30-minute expiry; distinguish weekly application limits from monthly provider quotas; document remaining assumptions.
  - Validation: Review requirements and official API documentation; validate HTML/local links and obsolete-content removal.
  - Completion notes: Revised design/3_game_info_ingress.html for CHIP’s selected direction. HTML tags/local links and removal of superseded sources/polling/paid recommendations validated; no runtime implementation performed.

### 2026-09-30

- Completed tasks: None yet.
- Validation: Read MVP, existing slice plans, models, and official provider documentation.
- Blockers: Publishing to design/ awaits clarification of AGENTS.md authority.
- Next: Finish reviewable proposal; publish if CHIP authorizes this exception.

### 2026-09-30 — Proposal published with CHIP authorization

- Completed tasks: BE-01, BE-02.
- Validation: Balanced HTML tags and resolved local links in design/3_game_info_ingress.html; reviewed current MVP and schema compatibility. No ingestion runtime implemented or credentialed API requests made.
- Affected files: design/3_game_info_ingress.html, AGENTS.md, and this epic’s proposal and area plans.
- Blockers: None for document delivery.
- Next: CHIP selects source pairing, bookmaker, coverage, budget, and freshness defaults before implementation planning.

### 2026-09-30 — On-demand free API proposal revision

- Completed tasks: BE-03.
- Validation: HTML tag balance, local links, required decisions, and obsolete-content checks passed. Reviewed official provider docs.
- Blockers: None for revision; free-account source behavior still needs a credentialed spike before implementation.
- Next: Review proposed numeric quotas, timezone, strict FBS membership, and automatic bookmaker rule; then create implementation tasks in both areas.
- design/3_game_info_ingress.html is authoritative; design history belongs in version control, not duplicate progress-area documents.

## Accepted implementation scope and current state

Governing design: [MVP](../../../design/1_mvp.html) sections 2–6; [ERD](../../../design/2_mvp_erd.png); [ingress design](../../../design/3_game_info_ingress.html) sections 1–8, as revised with CHIP’s acceptance.

Existing code has Game/Market/Selection models and an initial migration. main.py exposes health/readiness only; GamesPage.tsx is still a placeholder. Epic 1 read endpoints are planned but not implemented. Reuse those endpoints and schemas when available, rather than inventing a second games API. Ingress can begin on the completed persistence foundation; final API handoff depends on epic 1 BE-03/BE-04/BE-05.

Accepted: America/Los_Angeles calendar weeks; both teams FBS; free keys only; 20 attempts/week, 2 reserved until Sunday; 60-second cooldown; provider 10% reserve; deterministic per-game bookmaker selection; saved observations valid until kickoff/invalidation. No schedule, queue, page-load provider access, automatic retry, separate source spike, or status dashboard. Settlement and bet creation remain later MVP epics.

### Implementation contract

- Use explicit CFBD calendar and schedule windows, locally filtered to [Monday, next Monday). Cache calendar metadata by season; expire/reload it only within Refresh. January must consider the prior football season; year-crossing windows must not guess season numbering. A documented season-games query can supply classification/final metadata when needed; every extra call is budgeted. Document any mismatch between current schedule schema and historical game schema during client implementation.
- Get CFBD /info within an allowed attempt when initializing/refreshing account metadata; track its possible cost. Use a conservative call budget before any metadata call. Source reset timestamps control monthly accounting; unknown reset timing stays unknown. Odds headers reconcile credits; FAQ only establishes reset day, not exact hour. External key use can produce earlier exhaustion and must be surfaced.
- HTTP timeouts are bounded; a refresh has a 45-second total deadline. No retries. No DB transaction spans network calls. Use exclusive PostgreSQL advisory-lock ownership on a dedicated connection plus a durable refresh run and generation token. Lock loss invalidates the owner; later writes must confirm the run generation. Recover abandoned runs on subsequent requests without refunding uncertain calls or starting overlapping writers. Do not clear ownership just because the browser disconnected.
- Persist weekly attempt bucket and provider-call reservations before sending requests. A reservation becomes an accepted attempt on starting first provider work; entirely preflight-blocked requests leave attempts unchanged. Commit this transition before network dispatch, treating a crash between transition and dispatch conservatively. Reserve provider cost per call; count ambiguous outcomes and reconcile authoritative headers. Reject a call when it would breach the 10% reserve. Partial provider exhaustion may still permit the other stage.
- Integration tables proposed: provider_game_links (unique provider/external ID; canonical game FK; source season/type/teams/state/time); team_aliases (explicit provider team identity/name → canonical alias); quote_observations (game/market, external event, bookmaker, paired exact lines/prices, source/fetch timestamps, content identity); game_result_changes; refresh_runs; weekly_refresh_buckets; provider_quota_periods and provider_call_reservations. Use exact numeric types, UTC timestamps, uniqueness, and foreign keys. Retain failed/unmatched item reasons on runs; no unrelated generic framework.
- Keep one canonical spread market per real game for the current projection with two stable team selections. Changing chosen bookmaker updates projection/provenance together, leaving observations intact. Map provider data outside core UUIDs. Keep demo fixtures separate.
- POST /api/games/refresh has no caller-selected week; GET /api/games?window=current filters stored data. Route /refresh must precede /{game_id}. Existing unfiltered GET shapes/errors stay compatible. No refresh-status route.
- Response fields and HTTP statuses follow ingress section 7. reason vocabulary: refreshed, no_games, partial_failure, provider_failure, weekly_limit, sunday_reserve, cooldown, provider_budget, provider_rate_limit, refresh_in_progress, configuration_error, database_unavailable. remaining_refreshes includes Sunday-reserved attempts; retry_at is the earliest known local/provider restriction boundary, or null when unknown. Reserve/reset messages explain whichever restriction actually applies; do not promise provider availability on Monday.
- Stage outcome records distinguish fetched-and-applied, skipped-not-needed, rejected/quarantined, quota-blocked, and failed. Full success means required stages applied without unresolved invalid items; invalid/unmatched relevant items cause a partial-failure popup while valid items persist. Missing market on a valid response is normal unavailability, not provider failure. Empty current week is success. data_changed reflects committed changes so frontend can reload after partial success.
- GET projection uses current server time to suppress new-bet availability after kickoff without inventing completed/in_progress status. Clock-derived display labels must be distinguishable from provider-confirmed status. Future bet implementation rechecks this transactionally; this epic does not implement bets.

## Reviewable implementation tasks

- [x] BE-04 — Finalize accepted design and implementation planning
  - Status: complete
  - Scope: Adopt CHIP’s defaults, research public contracts, simplify frontend, and split runtime work below.
  - Dependencies: BE-03 and CHIP feedback.
  - Acceptance criteria: Design and sibling plans agree; completed document work is distinct from unimplemented runtime tasks.
  - Validation: Official documentation review; HTML/local-link and task-schema checks.
  - Completion notes: design/3_game_info_ingress.html and both plans revised September 30, 2026. No application code or credentialed requests.

- [ ] BE-05 — Configure provider clients and Pacific week rules
  - Status: not_started
  - Scope: SecretStr CFBD/odds keys, approved defaults and free-only hosts, safe HTTP clients, week/season-window resolution and timeout budgets; update .env.example without keys.
  - Dependencies: Existing settings; BE-04.
  - Acceptance criteria: Monday/Sunday/DST boundaries are exact; January season context uses provider calendar; no provider calls on startup/read/page load; credentials never appear in errors/logs; no automatic retries.
  - Validation: Frozen-clock week tests, HTTP contract fixtures for authenticated requests/errors/redaction, calendar overlaps and January postseason cases.
  - Completion notes: Pending.

- [ ] BE-06 — Add integration persistence migration
  - Status: not_started
  - Scope: Integration tables, unique identity/observation constraints, run ownership and quota records, auditable results; preserve original migration and canonical schema.
  - Dependencies: Completed epic 1 BE-01; BE-04.
  - Acceptance criteria: New upgrade creates only required tables/fields; decimal and timestamp precision correct; duplicate mappings/observations and orphan rows rejected; restart leaves ledgers intact.
  - Validation: Dedicated PostgreSQL migration/schema tests; downgrade/re-upgrade on disposable DB only; no migration on app startup.
  - Completion notes: Pending.

- [ ] BE-07 — Enforce atomic refresh and quota admission
  - Status: not_started
  - Scope: Ownership, weekly attempts, Sunday reservation, cooldown, conservative provider call accounting, reset metadata, and abandoned-run recovery.
  - Dependencies: BE-05, BE-06.
  - Acceptance criteria: At most 18 accepted attempts before Sunday and 20 on Sunday; repeated/concurrent tabs cannot overspend; rejected preflight consumes none; external-work failures consume one; Monday does not reset provider monthly usage; costs stay inside free allowances with 10% reserve.
  - Validation: PostgreSQL concurrent requests, restart recovery, fake provider timeouts, lock loss/fencing, unknown call outcomes, month/week boundaries, and provider external-use reconciliation.
  - Completion notes: Pending.

- [ ] BE-08 — Import canonical CFBD games/results
  - Status: not_started
  - Scope: Budgeted calendar/schedule/account calls, strict date/FBS filter, canonical identity upserts, source state mapping, and final-score audit.
  - Dependencies: BE-05 through BE-07.
  - Acceptance criteria: Provider season/week retained; both teams FBS; repeated imports duplicate nothing; rescheduling preserves identity; ambiguous/TBD/unknown status records quarantined; only explicit final with scores completes; cancellations require source evidence.
  - Validation: Provider-doc fixtures plus PostgreSQL repeated imports; Sunday finals, neutral sites, reschedules across window, FBS/FCS exclusion, invalid scores, final correction audit, stale source observations. Verify actual free-key response in normal integration if credentials are available; otherwise record that runtime limitation without treating web research as a live test.
  - Completion notes: Pending.

- [ ] BE-09 — Import paired current odds and observations
  - Status: not_started
  - Scope: Single US-region spread query, strict cross-feed aliases/unique kickoff matching, Decimal normalization, chosen-book retention/deterministic fallback, atomic current projection and quote history.
  - Dependencies: BE-08.
  - Acceptance criteria: Both sides from one bookmaker/observation; correct opposite signs/zero line; no fabricated odds or mixed books; future scheduled games only; absent valid quotes remove availability on successful scope response; failed calls preserve prior quotes; older responses cannot overwrite newer state.
  - Validation: Contract fixtures and PostgreSQL import tests for alias collisions, neutral orientation, missing/partial odds, book switching, rounding, zero line, ordering and repeat observations. Optional credentialed integration verifies free response and quota headers within limits.
  - Completion notes: Pending.

- [ ] BE-10 — Orchestrate bounded on-demand refresh
  - Status: not_started
  - Scope: Compose admission/CFBD/odds stages, independent commits, quota-blocked stage handling, no-games skip, deadline/cancellation behavior, run summaries and safe popup message generation.
  - Dependencies: BE-07 through BE-09.
  - Acceptance criteria: One accepted attempt spans all calls; no odds cost when no upcoming games; partial updates retained and reported as failure; timeouts/disconnected clients do not duplicate writers or refund unknown spending; no scheduled work.
  - Validation: Service integration tests exercise full/empty/partial/error paths, budget changes between stages, invalid relevant items, and interrupted request recovery.
  - Completion notes: Pending.

- [ ] BE-11 — Expose refresh and stored current-week APIs
  - Status: not_started
  - Scope: POST route and uniform response envelope; GET window=current filter on existing games router; cutoff-based availability using current time; preserve existing endpoints.
  - Dependencies: BE-10; epic 1 BE-03/BE-04/BE-05 for reusable read APIs and CORS.
  - Acceptance criteria: Contract in ingress section 7 documented in OpenAPI; static refresh route works; database-only GET; typed reason/status handling; Sunday games/results readable; unfiltered API and error semantics remain compatible; no credentials disclosed.
  - Validation: PostgreSQL API tests for 200/429/409/503/422, body fields, date filter, partial reload flag, order, server-clock kickoff cutoff, endpoint routing, health/readiness regressions and CORS.
  - Completion notes: Pending.

- [ ] BE-12 — Verify and document real ingress handoff
  - Status: not_started
  - Scope: Setup docs, key configuration, free-only usage/limit semantics, complete backend checks and frontend handoff; document integration evidence accurately.
  - Dependencies: BE-05 through BE-11.
  - Acceptance criteria: Isolated PostgreSQL tests pass; docs reproduce explicit refresh behavior and simple popup contract; live verification reported only if keys configured and calls made; missing free access is recorded without upgrading. All backend criteria met before area marked complete.
  - Validation: Backend suite plus bounded free-provider smoke test if available, migration drift, no-secret review, and documented sample full/partial/limit envelopes. No user DB deletion or external paid subscriptions.
  - Completion notes: Pending.

## Backend completion criteria

All BE-05–BE-12 complete and validated; explicit free-provider refresh persists current-week FBS games and paired spreads, reports failures/remaining attempts, and enforces durable concurrency, weekly, monthly, and kickoff constraints. Whole epic remains incomplete until FE-01–FE-02 also pass. Bet/settlement correctness is a future dependency, not claimed here.

### 2026-09-30 — Accepted defaults and detailed planning

- Completed tasks: BE-04 (documents/planning only).
- Validation: Read governing design, current models/main/settings, epic 1 state, and official CFBD Games/Info/tier docs and Odds API plans/v4/FAQ. Public documentation sufficient for planning; no account credentials or runtime API calls used.
- Blockers: No planning blockers. Runtime handoff awaits planned epic 1 read API/CORS work; actual free account access is checked during implementation, not by a separate source spike.
- Next: BE-05 and BE-06 when implementation is requested; dependent tasks remain unchecked.

### 2026-09-30 — Progress directory numbering

- Adopted design-number/part-number naming; moved this existing plan without changing task IDs, statuses, or completed work.
- Validation: Sibling plans and governing design links resolve after rename.
- Next: Continue the existing task sequence.
