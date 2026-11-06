# taskboard4-api

Task API

Owned by @ika100-demo.

## Quick start

```bash
devbox shell                  # enter the dev environment
devbox run quality            # ruff + mypy
devbox run test               # pytest with coverage
DATABASE_URL=postgres://localhost:5432/taskboard devbox run -- uv run uvicorn taskboard4_api.main:app --reload --port 8080
```

The app needs a Postgres database (`DATABASE_URL`) and refuses to start without it. Then `curl http://localhost:8080/health`.

`devbox run image-build && devbox run image-smoke` starts the container image next to a throwaway Postgres and checks it (needs Docker).

## Conventions

- Config from environment variables only
- `/health` (liveness) and `/ready` (readiness) on every HTTP service
- Structured JSON logging
- `devbox run <script>` is the only sanctioned entry point for tooling

See `CLAUDE.md` for the full agent workflow and `devbox.json` for the canonical recipes.

## Deploy

| Target | Command |
|---|---|
| Staging / prod | Open a PR in the platform gitops repo or `/instance:promote taskboard4-api --to <env>` |

Image: `ghcr.io/ika100-demo/taskboard4-api` — built and tagged automatically by CI.
