# Ralph task loop

One task at a time: ask Codex to implement it, run the normal automated tests, record completion, and make one local commit. Repeat until the selected tasks are complete or a task needs attention. Nothing is pushed automatically.

## Three files, three roles

- `progress/.../plan.md`: requirements and acceptance criteria. The agent reads it; the runner does not interpret its prose.
- `ralph/ingress-backend.json`: task sequence, dependencies, test commands, and retry/time limits.
- `ralph/ingress-backend.progress.json`: structured execution progress, referencing the plan by path and task ID. Contains statuses and evidence, not copied requirements.

The JSON progress file drives task selection and resumption. After passing tests, the runner updates it and mirrors the task checkbox/status/completion notes into `plan.md`. Code, structured progress, and plan updates go into the same task commit. The Markdown mirror expects the existing task-ID checklist format with `Status` and `Completion notes` fields; it never infers dependencies or commands from plan prose.

## Run

Use a Docker Sandbox terminal with Python 3.9+, Git, authenticated Codex CLI, and Docker available. Open it from your regular terminal with `sbx exec -it autopredict-dev bash`; SSH is optional. Configure your Git author identity there if needed. Commit this tooling and existing changes first; the loop requires a clean tree/index. Avoid editing the shared project from another window or agent while it runs.

```sh
make ralph-preview                       # Show tasks and checks; no edits/model calls
make ralph-preview RALPH_ARGS="--verbose" # Include exact commands when needed
make ralph                               # Run BE-07–BE-12
make ralph RALPH_ARGS="--through BE-07"    # Start with just one task
make ralph RALPH_ARGS="--resume"          # Continue after inspecting a stopped run
```

Launching `make ralph` explicitly authorizes generated progress and plan updates for this run, as CHIP requested. For a different plan use `RALPH_CONFIG=ralph/your-run.json`.

### Ingress frontend: FE-01 through FE-03

```sh
make ralph-preview RALPH_CONFIG=ralph/ingress-frontend.json
make ralph RALPH_CONFIG=ralph/ingress-frontend.json
make ralph RALPH_CONFIG=ralph/ingress-frontend.json RALPH_ARGS="--resume"
```

The frontend configuration runs FE-01 → FE-03 → FE-02, preserving stable IDs while respecting FE-02's dependency on the imported spread fix. Run the configuration without `--through FE-03` to include all three tasks. Completed backend prerequisites are recorded in the structured progress file. The loop uses one local commit per task.

Each task builds the existing frontend Docker image, mounts browser tests/configuration into a disposable container, installs Chromium and its OS dependencies there, and runs TypeScript/Vite checks plus Playwright. No host Node/browser installation, backend startup, database changes, or real API keys are required. Existing live-backend tests stay opt-in; controlled browser tests are mandatory and live-provider validation remains separate. Browser artifacts remain in the disposable container; runner command output is retained under `.git/ralph/`.

The equivalent CLI is:

```sh
python3 scripts/ralph.py run --config ralph/ingress-backend.json \
  --allow-plan-updates --from BE-07 --through BE-12
```

The default worker uses `workspace-write` with no approval prompts. The runner runs tests separately, so worker restrictions do not prevent independent verification. `--permissions danger-full-access` is available if explicitly chosen inside the external Docker Sandbox; this script itself does not isolate the agent from your machine. Keep real provider keys outside the shared directory.

## Tests and manual verification

The ingress configuration runs familiar commands: `make db`, `docker compose build backend`, and the backend pytest suite through a one-off Compose container with the tests mounted read-only. `RUN_POSTGRES_TESTS=1` enables the existing fixtures that create/drop disposable test databases on the sandbox PostgreSQL server. Provider keys are blanked; the real-key environment is not used. There are no special smoke/checker scripts or new test services.

The loop retains automated tests for quota/concurrency, matching, imports, partial failures, and API behavior. Test coverage still requires reviewing the task commits; a passing command alone cannot prove every requirement.

After the loop, CHIP manually runs the backend and checks `POST /api/games/refresh` without keys. Expected: HTTP 200, `success=false`, `reason=configuration_error`, a useful safe message and full envelope, no accepted refresh attempt or provider calls, and saved data preserved. Then configure keys outside the sandbox and perform real-provider verification separately. The loop records both manual checks as pending, never as passed.

## Slice 4: backend, then frontend

```sh
make ralph-preview RALPH_CONFIG=ralph/slice4.json
make ralph RALPH_CONFIG=ralph/slice4.json
make ralph RALPH_CONFIG=ralph/slice4.json RALPH_ARGS="--resume"
```

Commit the setup changes before launching inside the sandbox. One command runs all eight tasks: `ralph/slice4.json` lists `ralph/slice4-backend.json` (BE-01–BE-04), then `ralph/slice4-frontend.json` (FE-01–FE-04). A failed/blocked backend task prevents frontend work. Resume skips fully completed phases so an interrupted frontend run can retain its uncommitted work. Each task still uses the ordinary runner's checks, plan/progress mirror, lock and local commit. To select a range within one area, use `make ralph RALPH_CONFIG=ralph/slice4-backend.json` or the frontend config with the usual range arguments; task ranges are rejected for a multi-plan sequence.

Backend checks run migrations and API/accounting regressions in disposable PostgreSQL databases. BE-04 prepares the guarded browser fixture; final cross-area browser evidence is deferred until FE-04. The old plans predate ingress delivery; preserve the implemented ingress rather than repeating its work. Do not claim real-provider verification from fictional fixtures.

Frontend checks build `ralph/browser.Dockerfile` through the test-only `ralph/slice4-checks.compose.yml` overlay. The image combines the existing backend Python environment with Node 24 and Chromium, so neither Python nor Node needs installation on the host. Controlled browser tests run for each frontend task. FE-04 additionally starts the real API using the existing guarded `live_backend.py` helper, enables live desktop/mobile browser tests, and stops the fixture afterward. Its helper owns creation and cleanup of `autopredict_browser_*` databases; the application database is never used for score mutation. Provider keys are blank. Only existing `db` is needed; development frontend/backend containers are not started or stopped. Build caches contain only public dependencies and code.

Both plans and structured trackers remain separate; no combined copy of their requirements is created. These setup commands do not implement settlement or mark its tasks complete. Screenshot/test artifacts stay inside the disposable check container; runner output remains under `.git/ralph/`.

Baseline verification: the image/build and controlled browser suite pass. The live harness starts and cleans up its generated database, but existing pre-ingress live tests fail because their future fixture dates fall outside the current-week Games view and their expected game lists use unfiltered reads. BE-04 must prepare current-window-aware fixtures; FE-04 must update the live tests to the delivered current-window contract and add settlement acceptance. Do not hide these failures by skipping live tests or reverting the Games window behavior.

## Stop, inspect, resume

The loop has three attempts and a one-hour wall limit per task per launch. Failed checks feed their logs to another fresh Codex session. Exhausted limits, blocked work, unexpected file/Git edits, failed commits, or Ctrl+C stop the loop without discarding changes. Inspect the files, then use `--resume` to grant another bounded attempt allowance.

Local logs/results/recovery state live under `.git/ralph/` (or the equivalent Git directory). Structured task progress is committed; local diagnostics are not. Completed committed tasks are skipped. A repository lock prevents two Ralph runners from operating together. Workers must not edit design files, runner/configuration files, progress files, or Git state. The runner alone stages verified changes and commits; it does not bypass failing hooks/signing or perform resets/stashes.

These are workflow guardrails, not a security boundary against a malicious agent. Review source changes, hooks, and build configuration before running anything with real keys.

## Reuse

Copy the run configuration and structured progress file. Set their matching `plan` reference, task IDs/titles/statuses, completed prerequisite IDs, allowed source paths, check commands, and limits. Keep product requirements only in the referenced plan/design. Each check has `name`, `argv` (argument array), optional repository-relative `cwd`, and `timeout`. `{repo}` in an argument expands to the project root; no shell evaluation is performed. Keep environment overrides non-secret.

For multiple plans, add a sequence config with `{"version": 1, "configs": ["ralph/first.json", "ralph/second.json"]}` and select it with the same `RALPH_CONFIG` argument. Paths are repository-relative. No new Make target is needed. Single-plan configurations continue to work through the same commands.

Runner regression tests use temporary Git repositories and fake Codex executables:

```sh
python3 -m unittest discover -s scripts/tests -v
```

They do not spend model credits, launch the real task loop, or change this repository's commits.
