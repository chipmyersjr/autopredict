# AutoPredict

AutoPredict is a college football betting simulator for testing strategies with theoretical bets. View stored games and spreads, run the Random Strategy, and inspect saved simulations and bet history.

## Run locally

Open Docker Desktop, then run Make commands from the repository root:

```sh
make build
```

To use a private settings file outside the project, run `export ENV_FILE="$HOME/.config/autopredict/runtime.env"` in your terminal before using Make. All Make commands use that file; without the override they use the local development `.env`.

| Command | What it does |
| --- | --- |
| `make build` / `make up` | Build images, start PostgreSQL, apply migrations, seed demo data, and start both apps. |
| `make dev` | Start previously built containers without running migrations or seeds. |
| `make down` | Stop all services and preserve database data. |
| `make logs` | Follow service logs; Ctrl+C exits logs without stopping services. |
| `make status` | Show container status and health. |
| `make db` | Start PostgreSQL only. |
| `make migrate` | Apply database migrations after the initial build. |
| `make seed` | Load demo games, the Random Strategy, and the local user after the initial build; preserve existing records. |
| `make help` | List common commands. |
| `make ralph-preview` / `make ralph` | Preview or run the verified task loop; see [Ralph instructions](ralph/README.md). |

## Open the app

- [Frontend home page](http://127.0.0.1:5173/)
- [Swagger API docs](http://127.0.0.1:8000/docs)

## Settlement handoff

Send `POST /api/runs/{id}/settle` with no body to resolve saved Bets against
stored completed games with final scores; canceled games void Bets. This never
refreshes providers. Missing final scores stay pending. Retry after a lost
response, then reload `GET /api/runs/{id}` and `/api/runs/{id}/bets`: terminal
outcomes, timestamps and evidence are preserved without regrading. Creation-key
replays return the same simulation with current outcomes.

Profit uses saved stake/price/line and Decimal rounding once per Bet to cents.
Current bankroll is starting bankroll plus realized profit; available bankroll
also subtracts open stakes. ROI is a ratio (not a percentage). Four 10.00 Bets
on a 100.00 Run, with a win at 1.9500, loss, push and pending Bet, yield profit
-0.50, current 99.50, available 89.50 and ROI -0.0050. Voiding the pending Bet
finishes at 99.50. Dashboard bankroll totals sum independent simulations.

For disposable acceptance, start `frontend/tests/support/live_backend.py` with
`--metadata /tmp/browser.json --port 8017 --origin http://127.0.0.1:5187`
using the backend Python environment and blank provider keys. It migrates a
generated `autopredict_browser_*` database, seeds fictional current-week future
games with zero lines and 1.9500 prices, and removes the database/metadata on
termination. Create a Run through HTTP first. Then invoke the same helper with
`--metadata /tmp/browser.json --finalize-run RUN_UUID --results /tmp/results.json`.
Results are a JSON object keyed by known Run game UUIDs, each containing
`status` (`completed` or `canceled`), `home_score` and `away_score` (nonnegative
integers or null, permitting missing-score tests). Inspect saved sides to choose
win/loss scores; equal scores push these zero lines. `--mutate-run RUN_UUID`
still changes current labels/quotes and moves games into history for snapshot
checks. Neither helper writes Bet outcomes or exposes a production score API.
Remove caller-created results files afterward; never use development records.

`RUN_POSTGRES_TESTS=1` enables the backend regression suite, including a real
HTTP create/finalize/settle/reload test and fixture cleanup checks. Final browser
evidence at desktop/mobile sizes remains pending for FE-04. Fictional results
do not verify actual provider final-confirmation/Refresh integration, which
remains a separate, unperformed credentialed check.

## Game ingress handoff

After setup, use `make migrate` for existing databases. Configure server-side
`CFBD_API_KEY` and `ODDS_API_KEY` in your settings file and recreate the backend
after changes (`docker compose up -d --force-recreate backend`, with `ENV_FILE`
exported if used). Leave both blank for the missing-key check below. Use free
accounts only; unavailable free access is a recorded integration gap, never an
upgrade or a reason to fabricate data.

`GET /api/games?window=current` reads saved data only. Explicitly send
`POST /api/games/refresh` with no body or query to import the current Pacific
Monday–Sunday window, requiring both teams FBS. There is no background refresh,
automatic retry, or prior-week catch-up. The 45-second bounded operation allows
one writer across tabs. Of 20 shared attempts/week, 2 are reserved until Sunday;
accepted provider work consumes an attempt even on failure, with a 60-second
cooldown. Preflight rejection consumes none. Monthly provider accounting is
separate: a 10% reserve targets at most 900 CFBD calls / 450 Odds API credits.
External key use can exhaust these earlier; unknown provider reset times remain
unknown, and Monday does not reset provider allowance. No eligible upcoming games
means no odds request.

Frontend handoff: disable Refresh while pending, show one popup using `message`,
and reload the stored current-week GET whenever `data_changed` is true, including
partial failure. Use a generic failure popup for transport errors without an
envelope. No status polling is needed. HTTP 200 includes finished failures;
429 means preflight weekly/cooldown/provider rejection, 409 an active refresh,
503 unavailable database, and 422 invalid input. Inspect `success` and `reason`.
Representative envelopes (UUIDs/times/counts vary; examples assume Saturday):

```json
{"success":true,"reason":"refreshed","message":"Refresh successful. 19 refreshes remaining this week. 2 are reserved until Sunday.","remaining_refreshes":19,"reserved_for_sunday":2,"retry_at":null,"data_changed":true,"run_id":"00000000-0000-0000-0000-000000000001"}
{"success":false,"reason":"partial_failure","message":"Refresh failed to update all data. Successful updates were saved; failed stages kept saved data. 19 refreshes remaining this week. 2 are reserved until Sunday. Games/results updated. Spreads: Refresh failed: provider request failed or timed out. Saved data remains available.","remaining_refreshes":19,"reserved_for_sunday":2,"retry_at":null,"data_changed":true,"run_id":"00000000-0000-0000-0000-000000000002"}
{"success":false,"reason":"sunday_reserve","message":"Refresh failed: the remaining 2 refreshes are reserved until Sunday. 2 refreshes remaining this week. 2 are reserved until Sunday.","remaining_refreshes":2,"reserved_for_sunday":2,"retry_at":"2026-11-15T08:00:00Z","data_changed":false,"run_id":null}
```

CFBD owns status: explicit final/completed plus both valid scores is required for
completion; elapsed kickoff never implies completion. Unknown/postponed states
are quarantined. Saved scheduled status can remain after kickoff, when new
selections become unavailable. Quotes use one bookmaker's paired opposite lines
(including zero), Decimal `ROUND_HALF_UP` to 2 line / 4 price places, and finite
prices greater than one. Keep the prior valid book or choose the smallest stable
book key. Failed calls preserve quotes; successful scope responses without usable
quotes remove availability. Observations/provenance and existing bets are retained;
settlement is separate.

### Verification and pending manual checks

Automated tests use fake keys/mock transports and disposable PostgreSQL databases,
including concurrent admission/fencing, migration drift, and full/partial/error
responses. Run the runner's configured PostgreSQL-enabled backend suite for
verification; operational results belong in its plan evidence. These tests do
not establish real HTTP deployment or free-account access.

**Pending — CHIP's manual missing-key HTTP smoke test:** with both keys blank,
recreate the backend, confirm `curl -i http://127.0.0.1:8000/api/ready` returns 200,
then run `curl -i -X POST http://127.0.0.1:8000/api/games/refresh` without a body.
With no active refresh or weekly restriction, expect HTTP 200 and exactly:
`success=false`, `reason="configuration_error"`, `retry_at=null`,
`data_changed=false`, a non-null UUID `run_id`, and unchanged
`remaining_refreshes=N` (20 for an unused week). `reserved_for_sunday=R` is
`min(2,N)` before Sunday, otherwise 0. The exact message is
`Refresh failed: provider credentials are missing or were rejected. N refreshes remaining this week.`
plus ` R are reserved until Sunday.` when R is nonzero. No provider calls or
reservations should occur. Repeat the POST: the count stays unchanged, with no
new cooldown. Compare stored GET results before/after; they must be unchanged.
Existing active/weekly restrictions take precedence; do not delete ledgers to
force this check.

**Pending — later credentialed verification:** CHIP configures free keys and
performs one deliberate refresh after restrictions permit. Record actual status,
safe envelope, stored FBS games/results/paired quotes and quota headers/account
metadata; an empty week legitimately skips odds and does not verify odds access.
Record denied features, unmatched items, partial updates or unknown reset timing
accurately, retaining saved data without buying access. Neither manual check has
been performed by this implementation loop; never record keys or raw credentials
in evidence.
