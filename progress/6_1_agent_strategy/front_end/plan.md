# Design 6, part 1 — Agent Strategy frontend

Area status: `in_progress`

Planning status: ready. Current execution status and evidence are recorded in the task checklist and latest loop entries.

## Objective and governing design

Deliver the guided Strategy → Games → Finalize Run workflow, revisit-able execution progress, per-game failures and expandable saved Agent reasoning from [design/6_agent_strategy.html](../../../design/6_agent_strategy.html), especially sections 4–7. Use the settled API implementation contract in the [backend plan](../backend/plan.md). Preserve [MVP](../../../design/1_mvp.html) simulation/history/accounting, [ingress](../../../design/3_game_info_ingress.html) explicit Refresh/current-week saved quotes, and [shared Strategies](../../../design/4_shared_strategies.html).

No profile editor, model/tool controls, strategy categories, Preview UI, separate Agent results page, comparison dashboard, automatic settlement, eval system or prompt optimization. The backend owns predictions, eligibility, retry budgets, progress, accounting and research. The browser only submits a durable Run and displays its state.

## Existing implementation and bounded changes

- `GamesPage.tsx` currently chooses the first Random strategy, offers a separate decision preview, and renders `DryRunForm`. Replace those controls with one guided creation experience on the existing Games route; keep Refresh and current-week game/score/quote rendering.
- Keep existing Games/Runs/Dashboard navigation and `#/runs/{id}`. Put processing and saved results in the same Run detail route; returning through Run history must restore progress.
- Reuse the durable creation-intent recovery in `api/runs.ts` and `DryRunForm`: save request key/body before POST, replay the same key after uncertain delivery, and warn before abandoning a possibly accepted request.
- Retain imported `home`/`away` → saved team-name display, Pacific saved kickoff, completed-game scores, immutable quote provenance, settlement and exact P&L. The existing Saved Bets section is the place for Agent reasoning.

## Settled interaction and API implementation contract

### Guided creation

1. **Strategy:** Fetch active shared Strategies. Render accessible selectable cards/radio options for Random and FootballAnalysisExpert using server names/descriptions. Require a deliberate user choice, including when only one active option exists. Loading, empty and retryable error states must never silently pick a strategy. Inactive entries are unavailable.
2. **Games:** Read stored current-week games. Initially select all currently eligible games; provide Select All and individual toggles. Eligibility continues to require a scheduled future game and valid active paired spread; preserve complete role-side and team-name-side support. Cards show teams, Pacific kickoff, both stored lines/prices and available bookmaker provenance. Ineligible games stay visible with a reason. Initial selection happens once per loaded dataset; deselection is never undone by rerenders/polling.
3. **Finalize:** Show selected strategy, selected games, editable bankroll/stake/name, and the maximum committed stake if all selected games become Bets. Calculate that estimate with existing exact cents/BigInt utilities. Disable final submission for invalid money/name, no strategy, no eligible selected games, or maximum stake above bankroll. Back navigation retains choices. Display the server's final skipped-game outcomes when eligibility changes after review.

- Keep Refresh explicitly user-triggered. While editing, a changed-data reload removes newly ineligible selections and explains that the review changed; it must not silently re-add deselected/new games. If a previously selected game disappears, require review before final submission. Do not call a predictor during strategy selection, navigation, Refresh, rendering or loading a saved Run.
- Final submission creates exactly one saved intent using the selected strategy ID and existing RunCreate body. Freeze that intent during recovery; editing requires the existing deliberate discard flow. Disable duplicate submissions synchronously. Once POST returns an accepted Run, clear pending intent and navigate to its detail even if `bets=[]`.
- New accepted POST is 201, identical replay is 200; both return `{run, bets, skipped_games}` with `run.execution_status`. Preserve bounded safe handling for 404/409/422/503 and unknown delivery. A timeout does not mean prediction failed, and leaving the page does not cancel accepted work. Remove the preview client/UI and retire its browser tests in favor of creation coverage.

### Execution progress on existing Run detail

- Add shared client types matching backend BE-06: Run `execution_status` (`queued`, `running`, `completed`, `failed`) and execution timestamps; Bet nullable `reasoning`; expanded skip reasons; execution GET fields and ordered per-game states/counters. Keep execution completion separate from financial `Run.status` and settlement completion.
- Load owner-scoped `GET /api/runs/{id}/execution` alongside existing detail. Poll every 2 seconds while execution is queued/running, with one request at a time. Abort reads/timers on navigation/unmount; stopping browser polling never sends a cancellation request. Refresh errors retain last known progress and offer retry instead of claiming the Run stopped.
- Display server `completed_games / total_games`, queued/predicted/retrying/skipped counts, and per-game statuses including retries and safe failure labels. A prediction is not yet a persisted Bet; only ordinary final Run/Bets reads establish final outcomes. Do not calculate percentages from elapsed time or fabricate intermediate progress.
- On terminal execution, stop polling and reload existing detail/Bets once. Show successful Bet count and all skip reasons; all-failed execution remains a readable Run with zero Bets and safe explanation. Reopening from history obtains current persisted progress without resubmitting, refreshing providers, or running inference.
- Keep settlement unavailable until execution completed successfully. While processing show “Processing predictions,” rather than implying all recorded Bets already exist or are awaiting settlement. Financial metrics continue to reflect server values; pending/failed execution does not imply a financial win/loss. Historical Runs backfill execution completed and remain readable without research.

### Saved reasoning and comparison

- For each Agent Bet with reasoning, add a keyboard-accessible native details/summary disclosure in Saved Bets. Render the stored concise text as plain text, max 1,000 characters, alongside saved team/line/price/stake. Do not render it as executable HTML or a raw reasoning trace. Random/historical null reasoning has no empty disclosure.
- Preserve current result evidence, final scores, kickoff formatting, zero/null distinction, saved team labels, settlement retries and Run/Dashboard money display. Explain per-game skipped reasons separately from Bet reasoning.
- Compare strategies through existing named Run history/details and existing profit/ROI results. Strategy names must resolve for both types. No new comparison page or claims that a small result proves superiority.

## Tasks

- [x] FE-01 — Extend Run clients for Agent creation and persisted progress
  - Status: complete
  - Scope: Add Agent Strategy config types, execution/skip/reasoning response types, abortable progress GET and safe error labels; preserve creation identity and exact decimal fields; remove preview-client use.
  - Dependencies: Backend BE-06 API contract.
  - Acceptance criteria: Accepted empty-Bet response is valid; replay recovers the same Run; execution status is distinct from financial status; all new failures are readable without raw service details; no prediction outside final creation.
  - Validation: Type/build checks and intercepted browser contracts for 201/200, ownership/missing/invalid/inactive/conflict/database errors, response loss, exact request key/body preservation, progress schema, reasoning/null handling and abort behavior.
  - Completion notes: Extended Agent Run types, abortable progress reads, safe failure labels, and reasoning support; removed preview requests and adapted tests. Added intercepted client contracts. Whitespace check passed. Build/browser checks await runner verification because Node is unavailable and Docker access is denied. No protected-file edits or Git mutations performed. Independent checks: Whitespace passed; Start sandbox database passed; Build current backend and fixture dependencies passed; Build shared isolated browser image passed; Frontend build and controlled browser regressions passed. Files: frontend/src/api/runs.ts, frontend/src/api/strategies.ts, frontend/src/pages/GamesPage.tsx, frontend/src/pages/RunsPage.tsx, frontend/tests/agent-clients.spec.ts, frontend/tests/imported-spreads.spec.ts, frontend/tests/results-api.spec.ts, frontend/tests/runs.spec.ts, frontend/tests/strategies-live.spec.ts, frontend/tests/strategies.spec.ts, progress/6_1_agent_strategy/front_end/plan.md, ralph/agent-strategy-frontend.progress.json. Logs: .git/ralph/2e21aa4abb5195e3/FE-01-001.*. Automated browser checks use controlled data. FE-05 additionally requires real API/worker execution in a generated disposable PostgreSQL database with fake model/search responses. Actual Ollama/DuckDuckGo behavior is not established by these checks.

- [x] FE-02 — Replace preview and auto-selection with the guided creation flow
  - Status: complete
  - Scope: Build accessible strategy cards, preselected eligible-game step, Select All/toggles and Finalize review using existing Games and recovery components.
  - Dependencies: FE-01.
  - Acceptance criteria: Explicit strategy selection is required; current odds/bookmaker/teams/kickoff appear; initially eligible games select once; deliberate deselections survive; ineligible games show reasons; exact stake estimate and bankroll validation hold; only final submit creates a Run; Refresh stays separate.
  - Validation: Controlled Playwright tests for both strategies, no auto-choice, empty/inactive/error lists, role/team-name pairs, kickoff transition, initial/select-all/manual selection, back/forward state, changed/removed games after Refresh, valid/invalid money, maximum stake, double click, saved-intent replay/discard and no /decisions requests. Test keyboard use and 375px/1280px layouts.
  - Completion notes: Implemented guided Strategy → Games → Finalize creation with explicit strategy choice, preserved selections, Refresh review, exact stake validation, and durable request recovery. Added desktop/mobile coverage and adapted existing regressions. Whitespace check passed; build/browser checks await runner verification because Node/npm are unavailable and Docker access is denied. No protected-file edits or Git mutations. Independent checks: Whitespace passed; Start sandbox database passed; Build current backend and fixture dependencies passed; Build shared isolated browser image passed; Frontend build and controlled browser regressions passed. Files: frontend/src/api/games.ts, frontend/src/components/DryRunForm.tsx, frontend/src/pages/GamesPage.tsx, frontend/src/styles.css, frontend/tests/games.spec.ts, frontend/tests/guided-creation.spec.ts, frontend/tests/imported-spreads.spec.ts, frontend/tests/runs-live.spec.ts, frontend/tests/runs.spec.ts, frontend/tests/settlement-live.spec.ts, frontend/tests/strategies.spec.ts, frontend/tests/support/guided.ts, progress/6_1_agent_strategy/front_end/plan.md, ralph/agent-strategy-frontend.progress.json. Logs: .git/ralph/2e21aa4abb5195e3/FE-02-002.*. Automated browser checks use controlled data. FE-05 additionally requires real API/worker execution in a generated disposable PostgreSQL database with fake model/search responses. Actual Ollama/DuckDuckGo behavior is not established by these checks.

- [x] FE-03 — Add real persisted execution progress and recovery
  - Status: complete
  - Scope: Extend existing Run detail/history with processing states, polling lifecycle, per-game retry/skip labels, terminal reload and safe failed/unknown-delivery presentation.
  - Dependencies: FE-01, FE-02; backend BE-04–BE-06.
  - Acceptance criteria: Progress comes from server state, survives reload/navigation/page closure, and stops polling at terminal status. A stale response cannot alter another Run; polling failure does not resubmit. Partial and all-failed Runs are understandable; settlement is disabled while execution is incomplete or failed.
  - Validation: Controlled browser sequences for queued/running/retrying/completed/failed, stable count denominators, one in-flight poll, slow/out-of-order replies, progress failure/retry, repeated terminal responses, reload/history return, response-loss recovery, no job cancellation on navigation and no fabricated Bet/profit values.
  - Completion notes: Fixed duplicate progress reads during StrictMode replay and terminal-refresh races that dismissed detail retry errors. Preserved server polling, recovery, and settlement guards. Whitespace check passed; browser/build verification awaits runner because Node is unavailable and Docker access is denied. No protected-file edits or Git mutations performed. Independent checks: Whitespace passed; Start sandbox database passed; Build current backend and fixture dependencies passed; Build shared isolated browser image passed; Frontend build and controlled browser regressions passed. Files: frontend/src/pages/RunsPage.tsx, frontend/tests/execution-progress.spec.ts, frontend/tests/runs.spec.ts, frontend/tests/settlement.spec.ts, progress/6_1_agent_strategy/front_end/plan.md, ralph/agent-strategy-frontend.progress.json. Logs: .git/ralph/2e21aa4abb5195e3/FE-03-004.*. Automated browser checks use controlled data. FE-05 additionally requires real API/worker execution in a generated disposable PostgreSQL database with fake model/search responses. Actual Ollama/DuckDuckGo behavior is not established by these checks.

- [x] FE-04 — Display saved Agent reasoning without changing financial history
  - Status: complete
  - Scope: Add expandable reasoning to Saved Bets; preserve existing snapshot, score, provenance, settlement and Run comparison displays for both strategy types.
  - Dependencies: FE-01, FE-03.
  - Acceptance criteria: Agent reasoning is readable plain text behind an accessible disclosure; Random and historical Bets omit it; saved names/role labels, Pacific kickoff, zero final scores, snapshot prices and P&L remain intact after reload/settlement. No new result/comparison page.
  - Validation: Playwright fixtures for null/blank/1,000-character/special-character reasoning, keyboard expand/collapse, screen-reader name, no HTML execution, team-side label mapping, long text/mobile overflow, immutable snapshots, settlement response reload and strategy labels in history. Preserve Saved Bets/settlement/dashboard regressions.
  - Completion notes: Implemented accessible, plain-text saved reasoning disclosures with 1,000-character limits and mobile wrapping. Added desktop/mobile regression coverage for keyboard access, HTML safety, settlement persistence, snapshots, and strategy labels. Whitespace checks passed; browser/build verification awaits the runner because Node is unavailable and Docker access is denied. No protected files or Git state changed. Independent checks: Whitespace passed; Start sandbox database passed; Build current backend and fixture dependencies passed; Build shared isolated browser image passed; Frontend build and controlled browser regressions passed. Files: frontend/src/pages/RunsPage.tsx, frontend/src/styles.css, frontend/tests/saved-reasoning.spec.ts, progress/6_1_agent_strategy/front_end/plan.md, ralph/agent-strategy-frontend.progress.json. Logs: .git/ralph/2e21aa4abb5195e3/FE-04-005.*. Automated browser checks use controlled data. FE-05 additionally requires real API/worker execution in a generated disposable PostgreSQL database with fake model/search responses. Actual Ollama/DuckDuckGo behavior is not established by these checks.

- [ ] FE-05 — Prove the complete guided Random and Agent flows
  - Status: not_started
  - Scope: Add real-API desktop/mobile acceptance against guarded disposable PostgreSQL and a controlled worker/model/search fixture; record actual live Ollama smoke separately.
  - Dependencies: FE-01–FE-04; backend BE-07 fixture and worker startup support.
  - Acceptance criteria: Create each strategy only after final review; observe real persisted progress; close/reopen during processing; recover the same Run after response loss; inspect saved reasoning/skips; settle controlled final results and inspect unchanged server profit/ROI through existing views. Worker restart does not duplicate Bets. No developer/provider database mutations or live-key requirements for automated acceptance.
  - Validation: Production build, full controlled browser regressions and PostgreSQL-backed flows at 375px/1280px, keyboard and screenshot inspection, partial/all-failed/quote-change cases, worker restart, exact accounting checks and fixture/server/database cleanup. Manual local-model/keyless-DuckDuckGo run is conditional on the model and network being available; mark unperformed if unavailable.
  - Completion notes: Not implemented or validated.

## Execution order and completion criteria

Backend BE-01–BE-07 supplies the durable runtime; frontend FE-01 → FE-02 → FE-03 → FE-04 → FE-05 completes the user flow. Both areas must satisfy their task acceptance criteria. Completion means users can select either Strategy deliberately, submit an eligible Run, revisit persisted processing, inspect reasoning/skips and compare settled existing Run results. This plan records no task as implemented.

## Loop log

### 2026-11-19 — Initial Agent Strategy planning

- Completed task IDs: None.
- Validation: Reviewed design 6's guided workflow and revised native-SDK architecture; inspected GamesPage, DryRunForm, API clients, navigation, Run history/detail and existing controlled/live browser fixtures. Compared sibling backend contracts and failure/recovery states. No runtime tests were run for this documentation-only work.
- File layout: Replaced the empty `frontend/plan.md` placeholder with the repository-standard sibling `front_end/plan.md`; no implementation history existed to move.
- Blockers: No planning blockers. Actual Ollama/search acceptance requires external runtime configuration; deterministic automation does not.
- Next: Implement backend BE-01 first; begin FE-01 against delivered BE-06; complete live cross-area evidence in FE-05.

### 2026-11-19 — Keyless search selected

- Completed task IDs: None; implementation statuses unchanged.
- Decision: DuckDuckGo replaces hosted Ollama search behind the backend's existing tool interface. Frontend contracts and UI tasks are unchanged; no key-entry controls are needed.
- Validation: Updated FE-05's manual-smoke wording to match the revised design/backend plan. No browser tests run for this documentation edit.

### 2026-11-20 03:38 UTC — FE-01 Ralph execution

- Completed tasks: FE-01.
- Validation: Whitespace passed; Start sandbox database passed; Build current backend and fixture dependencies passed; Build shared isolated browser image passed; Frontend build and controlled browser regressions passed.
- Completion notes: Extended Agent Run types, abortable progress reads, safe failure labels, and reasoning support; removed preview requests and adapted tests. Added intercepted client contracts. Whitespace check passed. Build/browser checks await runner verification because Node is unavailable and Docker access is denied. No protected-file edits or Git mutations performed.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.

### 2026-11-20 03:45 UTC — FE-02 Ralph execution

- Completed tasks: FE-02.
- Validation: Whitespace passed; Start sandbox database passed; Build current backend and fixture dependencies passed; Build shared isolated browser image passed; Frontend build and controlled browser regressions passed.
- Completion notes: Implemented guided Strategy → Games → Finalize creation with explicit strategy choice, preserved selections, Refresh review, exact stake validation, and durable request recovery. Added desktop/mobile coverage and adapted existing regressions. Whitespace check passed; build/browser checks await runner verification because Node/npm are unavailable and Docker access is denied. No protected-file edits or Git mutations.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.

### 2026-11-20 03:52 UTC — FE-03 Ralph execution

- Completed tasks: FE-03.
- Validation: Whitespace passed; Start sandbox database passed; Build current backend and fixture dependencies passed; Build shared isolated browser image passed; Frontend build and controlled browser regressions passed.
- Completion notes: Fixed duplicate progress reads during StrictMode replay and terminal-refresh races that dismissed detail retry errors. Preserved server polling, recovery, and settlement guards. Whitespace check passed; browser/build verification awaits runner because Node is unavailable and Docker access is denied. No protected-file edits or Git mutations performed.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.

### 2026-11-20 03:55 UTC — FE-04 Ralph execution

- Completed tasks: FE-04.
- Validation: Whitespace passed; Start sandbox database passed; Build current backend and fixture dependencies passed; Build shared isolated browser image passed; Frontend build and controlled browser regressions passed.
- Completion notes: Implemented accessible, plain-text saved reasoning disclosures with 1,000-character limits and mobile wrapping. Added desktop/mobile regression coverage for keyboard access, HTML safety, settlement persistence, snapshots, and strategy labels. Whitespace checks passed; browser/build verification awaits the runner because Node is unavailable and Docker access is denied. No protected files or Git state changed.
- Next: Continue the configured task sequence; live-provider verification remains separately reported.
