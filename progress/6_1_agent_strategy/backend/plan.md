# Design 6, part 1 — Agent Strategy backend

Area status: `in_progress`

Planning status: ready. Current execution status and evidence are recorded in the task checklist and latest loop entries.

## Objective and governing design

Deliver the native-Ollama Agent Strategy, durable Run processing, and saved Bet reasoning alongside Random Strategy. Use [design/6_agent_strategy.html](../../../design/6_agent_strategy.html), sections 1–7, as the governing scope. Preserve [MVP](../../../design/1_mvp.html) execution/accounting, [ingress](../../../design/3_game_info_ingress.html) eligibility and immutable observations, and [shared Strategies](../../../design/4_shared_strategies.html). Coordinate with the [frontend plan](../front_end/plan.md).

The current design supersedes the earlier RAG outline: use the native `ollama` SDK, local inference, and our own keyless DuckDuckGo search adapter. Do not introduce LangGraph, a vector database, hosted inference, profile versioning, eval infrastructure, new tables, or a separate comparison dashboard. CHIP authorized additional execution/progress fields on existing tables on November 19 to support section 7, then selected DuckDuckGo instead of hosted Ollama search; the design reflects both decisions.

## Existing implementation and integration points

- `strategies.py` resolves valid stored selections and implements Random choice. Both the decisions endpoint and `runs.create_run()` currently invoke Random directly.
- Strategy type/config constraints and API schemas allow only Random. `seed_strategy.py` seeds its stable shared record.
- Run creation holds database locks while generating choices; it currently commits all Bets before returning. Creation-key replay, ownership, settlement, result evidence, saved quote provenance, and dashboard accounting already exist.
- There is no persisted execution progress or Run worker. Current lifespan only owns the database engine. Compose/Make start the database, API, and frontend.
- `frontend/tests/support/live_backend.py` already guards disposable test databases. Extend this facility for acceptance; never mutate development/provider games.

## Settled implementation choices and shared contract

These are implementation details under design 6, not a replacement product specification.

### Persistence and strategy interface

- Add `Bet.reasoning`, nullable `VARCHAR(1000)`, through an additive migration after the actual migration head (currently `0005`). Preserve existing execution and settlement snapshots. Agent output must contain trimmed nonblank reasoning of 1–1,000 characters; Random/historical Bets retain null. Add matching serializers to every Bet response, including creation/replay, history, settlement and dashboard recent results.
- Extend Strategy constraints/schema to `random` and `agent`. Random config remains null/empty; Agent config is exactly `{"profile":"FootballAnalysisExpert"}` for the initial registered profile. Other registered profiles can later use the same engine; reject unknown IDs, extra keys and caller-supplied paths/prompts/model settings.
- Store the operational profile at `backend/app/agent_profiles/FootballAnalysisExpert.md`; load it only through a server-owned ID-to-path registry. Its behavior follows design section 2. Seed a stable shared Agent Strategy idempotently without replacing the Random record or overriding existing records.
- Define one async per-game `predict(input) -> prediction` interface. Input contains the game identity, teams, kickoff and eligible selection snapshots. Output contains a supplied selection ID and nullable reasoning. Random chooses uniformly from candidates; Agent uses the generic engine plus registered profile. The application resolves all IDs/line/price/provenance and rejects foreign selections. Only Run execution invokes prediction.
- Retire `POST /strategies/{id}/decisions` with a documented 410 response directing callers to Run creation; it must perform no prediction or research. Remove its UI use in the sibling plan.

### Durable execution without new tables

- Keep financial `Run.status` (`open`/`completed`) separate from `execution_status`: `queued`, `running`, `completed`, `failed`. Historical Runs backfill execution as completed. Use additional Run fields for execution timestamps, safe failure message, owner token, increasing generation and lease expiry. Use RunGame fields for per-game state, attempt count and the input/validated prediction JSON needed for recovery. Do not persist chat transcripts, internal model thinking, search result lists or profile/model versions.
- Per-game states: `queued`, `analysing`, `retrying`, `predicted`, `bet_created`, `skipped`. Preserve requested order and the existing skip reasons, adding exactly `agent_unavailable`, `research_failed`, `invalid_agent_decision`, and `quote_changed` from design section 4.
- Run a dedicated `python -m app.run_worker` process using the backend image. Initially process one game at a time and one Run at a time. PostgreSQL claims/leases and fencing must prevent duplicate writers even if two worker instances accidentally run. A bounded `--once` mode permits deterministic tests. A task is persisted before work begins; a page closing does not cancel it.
- Commit an attempt counter before calling the predictor. At most two prediction attempts per game, including interruption recovery and quote-change retries. Completed per-game predictions survive restart; an interrupted uncommitted attempt can be retried only within that budget. Never promise exactly-once external inference after a crash; guarantee at most one persisted Bet per Run/game and no new execution from HTTP replay.
- Defaults: 180-second wall limit per prediction attempt, at most 8 model turns and 6 search calls per attempt, 5 search results per call, bounded returned snippet text. These limits are server settings, not model-controlled. Use a 240-second renewable worker lease and 15-second heartbeat; stale generations cannot persist results. No DB transaction remains open during inference/search.
- Store validated predictions as operational RunGame state, then write all successful Bets and final skips atomically in one short finalization transaction. Lock Games in stable UUID order before Run/RunGame and dependent quote/selection writes, compatible with existing creation/settlement. Recheck ownership generation, current eligibility, exact captured quote/provenance and bankroll before committing.
- If a quote changes, refresh the eligible inputs and retry outside locks if an attempt remains; after a second change, skip `quote_changed`. Kickoff/status/no-pair failures use existing eligibility skips. Failures on one game do not discard other valid predictions or silently use Random.
- An accepted Run where every game ultimately skips remains available with execution failed, zero Bets, full per-game reasons and its untouched bankroll. Do not invent settlement profit, ROI or completed financial results for it. Pending/failed execution cannot settle; return 409. For successful execution, financial status stays open until the existing explicit settlement completes it. Preserve existing dashboard accounting formulas; execution progress is not realized profit or a Bet outcome.

### API contract for the frontend

- Retain the existing `POST /api/runs` body and required `Idempotency-Key`. Validate ownership, strategy/profile, requested games, initial eligibility and maximum stake before accepting. No eligible games remains 409; invalid amounts/insufficient bankroll remain 422; unknown resources 404; inactive strategy 409; unavailable database 503.
- New accepted creation returns 201 with the existing `{run, bets, skipped_games}` envelope, a persisted Run ID and `run.execution_status=queued`; Bets are initially empty. Identical replay returns 200 with current persisted state for that same Run. Different payload with the same key returns 409. Both Random and Agent use this contract and the shared worker. No inference occurs in the HTTP request or a GET.
- Add `execution_status` and execution timestamps to Run read/creation/replay shapes. Preserve all existing money strings, UTC timestamps, ordering, ownership and accounting fields. Existing Runs read as execution completed.
- Add owner-scoped `GET /api/runs/{id}/execution`: `{run_id, status, total_games, completed_games, predicted_games, skipped_games, retrying_games, queued_games, games, message}`. Here `skipped_games` is a count; each ordered `games` item contains `{game_id, state, attempts, skip_reason}`. `completed_games` counts predicted/bet-created/skipped items, not attempts; counters derive from one consistent snapshot and never exceed total_games. Return a short safe message for terminal failure. Unknown/other-user IDs return 404. Return no raw inputs, prompts, secrets or transcripts.
- HTTP acceptance only acknowledges durable work; it does not imply Bets were created. After terminal progress, frontend reloads the ordinary Run/Bets endpoints for final persisted results. Polling reads never execute jobs. Browser polling failure does not imply job failure.

### Ollama integration and operational boundary

- Add and lock `ollama` and `ddgs`. Use a dedicated `AsyncClient.chat()` for local inference, default `OLLAMA_HOST=http://host.docker.internal:11434`, `OLLAMA_MODEL=gpt-oss:20b`. Keep host/model server-configured; no automatic hosted inference fallback or model download from API requests. This feature requires no Ollama or search API key.
- Implement a provider-independent `web_search(query)` adapter backed by `DDGS(timeout=10).text(query, backend="duckduckgo", max_results=5)`. Explicitly select DuckDuckGo rather than `auto` or multi-provider fallback. Normalize validated `title`/`href`/`body` results to title/URL/snippet, cap returned text and avoid crawling returned URLs. Reject blank/overlong queries; timeouts, rate limits, blocking and no usable results become a typed research failure. Keep synchronous DDGS work off the async loop with bounded concurrency and a finite transport timeout; cancellation must not spawn uncontrolled retries or late writes. Keep all requests within the existing per-attempt tool/time limits. The application owns the two-attempt policy; inspect and bound library retry behavior. Ensure unrelated environment credentials are not implicitly sent to local inference or search.
- A fresh message history per game supplies profile, allowed selection IDs/context, and only the `web_search(query)` tool. Let the model request research; execute only allowlisted tools with validated arguments and bounded responses. Append each assistant tool call and corresponding tool result before the next chat. Treat retrieved text as evidence, never as execution instructions. Validate final JSON selection/reasoning and resolve it against the original supplied candidates. Search/tool errors, empty unusable results and exhausted tool budget map to `research_failed`; local connection/model/deadline errors to `agent_unavailable`; malformed/foreign output to `invalid_agent_decision`.
- Extend Compose/Make build, dev, stop, logs and status to include the durable worker with the same private ENV_FILE support. Apply migrations/seeds before starting worker/API. Worker restart uses stored leases; API startup and ordinary reads do not run research. Random remains usable when Ollama/search are unconfigured.
- Implementation references checked November 19: official [Ollama SDK](https://github.com/ollama/ollama-python) and [tool calling](https://docs.ollama.com/capabilities/tool-calling), plus the community [DDGS library](https://github.com/deedy5/ddgs). Search still sends queries to an external service, but requires no key. DDGS is not an official DuckDuckGo API and live reliability must be tested separately from mocks.

## Tasks

- [x] BE-01 — Add Agent Strategy and durable execution persistence
  - Status: complete
  - Scope: Add the reasoning, execution and per-game operational fields/constraints and additive migration; extend response/domain types and skip enums.
  - Dependencies: Existing ingress/settlement schema.
  - Acceptance criteria: No new tables; old data backfills safely; profile/config, reasoning length and execution-state consistency are validated; current money/evidence constraints and unique Run/game/key guarantees remain intact.
  - Validation: Disposable PostgreSQL upgrade/downgrade/re-upgrade, Alembic drift, invalid configuration/state/reasoning constraints, legacy Run/Bet reads and immutable snapshot checks. Downgrade must refuse incompatible Agent data rather than silently remove it.
  - Completion notes: Corrected the persistence regression to assert PostgreSQL’s exact overlength error and verify the 1,000-character boundary. Syntax and whitespace checks passed. PostgreSQL tests require runner verification because Docker access is denied here. Runner-owned files and Git state were left untouched. Independent checks: Whitespace passed; Start sandbox database passed; Build backend dependencies passed; Backend regressions with disposable PostgreSQL databases passed. Files: backend/app/models.py, backend/app/runs.py, backend/app/schemas.py, backend/tests/test_agent_persistence.py, migrations/versions/0006_agent_execution.py, progress/6_1_agent_strategy/backend/plan.md, ralph/agent-strategy-backend.progress.json. Logs: .git/ralph/d796df80c525cf1e/BE-01-002.*. Automated verification uses disposable databases and controlled model/search responses. Actual local Ollama plus live DuckDuckGo verification is separate; no profitable-strategy claim or live-service verification is implied. Final cross-area browser proof belongs to FE-05.

- [ ] BE-02 — Add native Ollama clients and the server-owned profile
  - Status: not_started
  - Scope: Add locked Ollama/DDGS dependencies and local model settings, registered Markdown profile, keyless DuckDuckGo search adapter and explicit shared Strategy seed.
  - Dependencies: BE-01.
  - Acceptance criteria: Local model/host are configurable; no model/search key is required; DuckDuckGo is selected explicitly; the generic search tool returns bounded normalized snippets/URLs and surfaces blocked/empty requests; unknown profiles/paths are rejected; repeat/concurrent seeding preserves existing Strategies; Random requires no research service.
  - Validation: Mocked local client and DDGS adapter tests for transport/header/timeouts, exact backend selection, query validation, normalization, empty/malformed results, throttling/blocking, cancellation and credential isolation; profile lookup/path rejection, resource cleanup, idempotent seeds and Docker packaging. No actual model pull, search call or key required for automated tests.
  - Completion notes: Not implemented or validated.

- [ ] BE-03 — Implement shared predictors and the bounded Agent tool loop
  - Status: not_started
  - Scope: Add registry/protocol, Random adapter and generic Agent predictor using the registered profile and native chat/search loop.
  - Dependencies: BE-02.
  - Acceptance criteria: Both return the same typed selection decision; Agent reasoning is concise and valid; autonomous tool exchanges are bounded; selection/line/price/provenance cannot be fabricated; no random fallback or cross-game state leakage.
  - Validation: Deterministic Random injection, multi-turn/multiple-tool mocked exchanges, bad tool arguments, unknown tools, search errors/rate limits/blocking/empty results, unavailable model, deadlines/budget exhaustion, invalid JSON/foreign IDs/blank or overlong reasoning, malicious retrieved instructions and clean failure classifications.
  - Completion notes: Not implemented or validated.

- [ ] BE-04 — Build durable Run claims, progress and restart recovery
  - Status: not_started
  - Scope: Add worker module, queued claims, leases/heartbeat/fencing, persisted per-game attempts/results and deterministic one-shot execution support.
  - Dependencies: BE-01, BE-03.
  - Acceptance criteria: Work survives page closure and worker restart; two workers cannot persist duplicate outcomes; no inference under DB locks; max two attempts across restart; finished game work is retained; ordered progress and counters reflect persisted state.
  - Validation: PostgreSQL multi-worker/process tests, expired/live leases, stale writer rejection, failure before/after each durable boundary, heartbeat loss, graceful shutdown and restart, attempt budget, progress bounds and no model work on GET.
  - Completion notes: Not implemented or validated.

- [ ] BE-05 — Refactor creation and atomic best-effort Bet finalization
  - Status: not_started
  - Scope: Persist accepted requests before prediction; dispatch both strategy types through worker; capture/revalidate quote inputs, retry once where permitted, commit successful Bets and final skips atomically.
  - Dependencies: BE-04.
  - Acceptance criteria: Creation replay is durable and never starts another job; same-key conflict is safe; eligibility/bankroll and immutable saved inputs hold; quote changes cause fresh-input retry then skip; some game failures preserve successes; all-skipped Runs remain inspectable without fabricated accounting; settlement is blocked until successful execution completion.
  - Validation: Concurrent same-key POSTs, crash/response loss around acceptance/final commit, quote/alias/selection changes during inference, kickoff crossing, 50→47 example, all failed, invalid bankroll, injected rollback, duplicate finalization, unchanged historical reasoning and existing settlement/dashboard numeric oracles.
  - Completion notes: Not implemented or validated.

- [ ] BE-06 — Expose creation, progress and reasoning APIs
  - Status: not_started
  - Scope: Wire 201/200 accepted/replay responses, owner-scoped execution GET, extended Run/Bet reads, new skips and retired preview route; update OpenAPI and regressions.
  - Dependencies: BE-05.
  - Acceptance criteria: The shared frontend contract above is observable for both strategy types; progress is read-only and internally consistent; no prediction on legacy preview, history, settlement or dashboard reads; secrets/internal traces never appear in responses.
  - Validation: HTTP contract tests for acceptance/replay/processing/partial/terminal failure, ownership/404/409/410/422/503, snapshot consistency, ordering, all Bet serializers and no inference during reads. Keep creation/ingress/settlement/dashboard regression coverage.
  - Completion notes: Not implemented or validated.

- [ ] BE-07 — Integrate worker startup and prove the backend handoff
  - Status: not_started
  - Scope: Wire worker into existing Docker/Make lifecycle and seed startup; extend guarded disposable fixture support and concise operational documentation for local inference/keyless DuckDuckGo connectivity.
  - Dependencies: BE-01–BE-06.
  - Acceptance criteria: One normal app startup includes a persistent worker; controlled real-API Random and Agent Runs complete, replay, reopen and settle with correct accounting; worker restarts recover safely. Backend proof is independent of later FE-05 browser acceptance; label actual Ollama/search verification separately.
  - Validation: Full backend suite with RUN_POSTGRES_TESTS=1, disposable actual-HTTP acceptance with injected model/search stubs, Compose lifecycle, worker restart and database cleanup. Manual host-to-container local Ollama + keyless DuckDuckGo smoke when the local model and network are available; never claim mocks establish live service behavior or profitable predictions.
  - Completion notes: Not implemented or validated.

## Execution order and completion criteria

BE-01 → BE-02 → BE-03 → BE-04 → BE-05 → BE-06 → BE-07. FE-01 may implement the settled types once BE-06 lands. All seven backend tasks need implementation and validation before backend completion; full epic acceptance also requires frontend FE-05. No task is complete from this planning pass.

## Loop log

### 2026-11-19 — Initial Agent Strategy planning

- Completed task IDs: None.
- Validation: Reviewed design 6 and governing prior documents; inspected current Strategy/Run/Bet models, creation/preview/settlement/read paths, settings, SDK sources, Compose/Make and frontend recovery/fixtures. Runtime tests were not run for this document-only work.
- Design clarification: CHIP approved execution/progress fields on existing tables; updated only design 6 section 5. Native Ollama and the guided section-7 workflow govern this plan.
- Blockers: No planning blockers. Live smoke requires a running local model and network search access; automated acceptance uses controlled responses.
- Next: Implement BE-01; preserve prior epic plans and existing runtime behavior except the explicitly superseded prediction/creation flow.

### 2026-11-19 — Keyless search selected

- Completed task IDs: None; implementation statuses unchanged.
- Decision: CHIP selected DuckDuckGo instead of hosted Ollama search. Updated design 6 and affected BE-02/BE-03/BE-07 details; retain a provider-independent tool and the existing bounded failure policy.
- Validation: Checked DDGS's documented explicit DuckDuckGo backend, timeout and result shape. No live search/model execution or dependency installation performed.
- Next: Implement the revised tasks without adding an Ollama search key requirement.

### 2026-11-20 02:36 UTC — BE-01 Ralph execution

- Completed tasks: BE-01.
- Validation: Whitespace passed; Start sandbox database passed; Build backend dependencies passed; Backend regressions with disposable PostgreSQL databases passed.
- Completion notes: Corrected the persistence regression to assert PostgreSQL’s exact overlength error and verify the 1,000-character boundary. Syntax and whitespace checks passed. PostgreSQL tests require runner verification because Docker access is denied here. Runner-owned files and Git state were left untouched.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.
