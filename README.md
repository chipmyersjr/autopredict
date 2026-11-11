# AutoPredict

AutoPredict is a college football betting simulator for testing strategies with theoretical bets. View stored games and spreads, run the Random Strategy, and inspect saved simulations and bet history.

## Run locally

Open Docker Desktop, then run Make commands from the repository root:

```sh
make build
```

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

## Open the app

- [Frontend home page](http://127.0.0.1:5173/)
- [Swagger API docs](http://127.0.0.1:8000/docs)
