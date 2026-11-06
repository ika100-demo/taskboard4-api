---
spec_id: 002-keep-tasks-in-postgres-answer-503-and
title: Keep tasks in Postgres, answer 503 and report not ready while the database is down
status: done
priority: P1
shape: service-python
parent: ika100-demo/taskboard4-gitops:001-persistent-tasks-in-postgres-with-a-web
---

# 002 — Keep tasks in Postgres, answer 503 and report not ready while the database is down

## Problem

The taskboard4 Task API can create and list tasks, but it keeps them in process memory: every restart or redeploy wipes them, and the API cannot run more than one instance without each instance seeing different tasks. The only way to use tasks today is to call the API by hand; the web app still shows the template starter page and does not talk to the API. People who want to record what needs doing therefore have nowhere durable to put it and no screen to work in. This feature keeps tasks in a Postgres database owned by the system, so they survive restarts and are shared by every API instance, and lets people see and create tasks in the web app.

## System context

Slice of the system plan `001-persistent-tasks-in-postgres-with-a-web` in `ika100-demo/taskboard4-gitops` for `taskboard4-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given tasks "A" (no due date) and "B" (due `2026-12-31`) were created through `POST /tasks`, when every instance of the Task API is restarted and a caller then sends `GET /tasks`, then the response is `200` with both tasks, oldest first, each with the same `id`, `title` and `due_date` as returned when it was created.
- **AC-001.2** Given the Task API runs as two instances (as it does in dev), when a caller creates a task through `POST /tasks` and then sends `GET /tasks` ten times, then every one of the ten responses contains that task, whichever instance answers.
- **AC-001.3** Given the persistent storage, when callers use `POST /tasks` and `GET /tasks`, then the existing request and response contract is unchanged: `201` with `{id, title, due_date}`, titles trimmed and 1 to 200 characters, `due_date` a `YYYY-MM-DD` calendar date or `null` (past dates accepted), `422` naming the offending field with no task stored, and `GET /tasks` a bare JSON array oldest first.
- **AC-001.4** Given the database is unreachable, when a caller sends `POST /tasks` with a valid body or sends `GET /tasks`, then the response is `503` within 10 seconds, and no task is created.
- **AC-001.5** Given the database is unreachable, when the API's readiness endpoint is checked, then it reports not ready; and given the database becomes reachable again, when a caller sends `GET /tasks`, then the response is `200` with all tasks created before the outage, without the API being restarted.

### Contract

The Task API (`taskboard4-api`) serves the web app's Next.js server. In dev the base URL is
`TASKBOARD4_API_URL=http://taskboard4-api`. The request/response contract of component spec
001-create-and-list-tasks is unchanged; this plan adds the `503` outcome and the readiness behaviour.

**Task object** (JSON): `{"id": string, "title": string, "due_date": string | null}`. `id` is a non-empty
opaque string (a UUID today; callers must not parse it). `title` is trimmed, 1 to 200 characters.
`due_date` is `"YYYY-MM-DD"` or `null`. No other fields; callers ignore unknown fields if any appear.

### `POST /tasks`

- Request: `Content-Type: application/json`, body `{"title": string, "due_date": string | null}`;
  `due_date` may be omitted (same as `null`). The web app sends `due_date: null` for an empty date field.
- `201 Created`: body is the created Task object, title trimmed.
- `422 Unprocessable Entity`: validation failed, no task stored. Body is FastAPI's standard
  `{"detail": [{"loc": ["body", "<field>"], "msg": string, "type": string}, ...]}`; `loc[-1]` names the
  offending field (`title` or `due_date`). An invalid JSON body also answers `422`. Validation runs before
  the database is touched, so `422` is returned even while the database is down.
- `503 Service Unavailable`: the database is unreachable or did not answer in time; no task stored. Body
  `{"detail": "database unavailable"}`.

### `GET /tasks`

- `200 OK`: a bare JSON array of Task objects, oldest first (creation order across all instances); `[]`
  when there are none. No pagination.
- `503 Service Unavailable`: the database is unreachable or did not answer in time. Body
  `{"detail": "database unavailable"}`.

### Probes (platform, not the web app)

- `GET /health`: `200 {"status": "ok"}` whenever the process runs; never touches the database.
- `GET /ready`: `200 {"status": "ready"}` when `SELECT 1` succeeds; `503 {"status": "not ready"}` when it
  fails or times out.

### Errors

- Error bodies are JSON with a `detail` key: a list of validation entries for `422`, a string for `503`
  and for unexpected `500`s.
- The web app maps outcomes as follows. `GET /tasks`: only `200` with a JSON array counts as success; any
  other status (`503`, `500`, `404`, ...), a malformed body, a connection error or a timeout shows "Tasks
  could not be loaded. Please try again later." `POST /tasks`: only `201` with a Task object counts as
  success; any other status (including `422`, which cannot happen after the web app's own title check,
  and `503`), a malformed body, a connection error or a timeout shows "The task could not be saved.
  Please try again." with the form kept and nothing added to the list.
- A caller treats any status this contract does not list exactly like `503`: a failure, with no
  assumption that a task was or was not stored. The web app does not retry automatically.
- The web app logs the failure on its server (status or error kind, no task content beyond the id);
  error details from the API are never shown to the person.

### Timeouts

- **Web server -> API:** `GET /tasks` and `POST /tasks` each with a 5 s total timeout (connect plus
  response); on timeout the call counts as failed (see Errors). No retries.
- **API -> Postgres:** connect timeout 3 s, statement timeout 5 s, waiting for a pooled connection at most
  2 s; any of them expiring answers `503`. Together the API answers within 10 s in the worst case
  (AC-001.4); in practice an unreachable database answers in about 3 s.
- **`/ready`:** the database check uses a 0.5 s timeout so the probe answers within the kubelet's default
  1 s probe timeout; on expiry it reports `503 not ready`.
- **Database down:** the API keeps running (liveness stays green), answers `503` on task calls, and is
  taken out of the Service by readiness. With both instances not ready, the Service has no endpoints and
  the web app's calls fail fast with a connection error, which it treats as above. When the database
  returns, the next request opens a fresh connection; no restart is needed (AC-001.5).
- **API down or slow:** the web page still renders within the 5 s budget with the load message
  (AC-001.11); a create shows the save message (AC-001.12).

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`

### Notes for this repo

This spec supersedes component spec 001-create-and-list-tasks: withdraw its AC-001.10
("tasks gone after restart") and drop its non-goal against persistence and multiple instances,
through `/component:spec --amend 001` in this repo; the other criteria of spec 001 stay and their
tests must keep passing against Postgres. Connection comes from DATABASE_URL (accept both
`postgres://` and `postgresql://`), injected by the platform's postgres resource.

## Stories

As an API caller (the web app's server, scripts, people), I want the tasks I create to still be there after the Task API restarts or is redeployed, so that I can rely on it as the record of what needs doing.

As an API caller, I want every instance of the Task API to show the same tasks in the same order, so that it does not matter which instance answers me.

As an API caller, I want a clear `503` within a bounded time when the database is down, and the API to recover without a restart once the database is back, so that I can show a "try again" message instead of hanging or getting stale data.

As the platform operating the service, I want the readiness check to report the database's state and the liveness check not to, so that an outage takes instances out of rotation instead of restarting them.

This spec supersedes component spec 001-create-and-list-tasks where they conflict: spec 001's AC-001.10 (tasks gone after a restart) and its non-goal against persistence and several instances no longer hold; spec 001 is amended separately. All other criteria of spec 001 keep holding (AC-002.3).

## Acceptance criteria

- **AC-002.1** Given tasks "A" (no due date) and then "B" (`due_date` `"2026-12-31"`) were created through `POST /tasks`, when the service is stopped and started again over the same database and a caller sends `GET /tasks`, then the response is `200` with both tasks, "A" before "B", each with the same `id`, `title` and `due_date` as returned when it was created. (system AC-001.1)
- **AC-002.2** Given two instances of the service run over the same database, when a caller creates task "A" through instance one, then task "B" through instance two, and then sends `GET /tasks` to each instance, then both answer `200` with the same list in which "A" comes before "B", each with the `id`, `title` and `due_date` returned at creation. (system AC-001.2)
- **AC-002.3** Given the service runs with a reachable database, when the criteria AC-001.1 to AC-001.9, AC-001.11 and AC-001.12 of spec 001-create-and-list-tasks are checked against it, then every one of them holds unchanged (status codes, `{id, title, due_date}` objects, trimming, 1 to 200 character titles, `YYYY-MM-DD` or `null` due dates, `422` naming the field with no task stored, bare JSON array oldest first). (system AC-001.3)
- **AC-002.4** Given the database is unreachable, when a caller sends `POST /tasks` with an invalid body (for example `{"title": ""}`, `{"title": "x", "due_date": "2026-13-01"}` or a body that is not valid JSON), then the response is `422` exactly as with a reachable database, naming the offending field where there is one, and not `503`. (system AC-001.3)
- **AC-002.5** Given the database is unreachable (refuses or drops connections), when a caller sends `POST /tasks` with a valid body or sends `GET /tasks`, then the response is `503` with the body `{"detail": "database unavailable"}` within 10 seconds of the request. (system AC-001.4)
- **AC-002.6** Given the database accepts connections but does not answer a query (for example it is paused or a lock blocks it), when a caller sends `POST /tasks` with a valid body or sends `GET /tasks`, then the response is `503` with the body `{"detail": "database unavailable"}` within 10 seconds of the request. (system AC-001.4)
- **AC-002.7** Given a `POST /tasks` with a valid body was answered `503` during an outage, when the database is reachable again and a caller sends `GET /tasks`, then the list does not contain a task with that title. (system AC-001.4)
- **AC-002.8** Given the database is reachable, when `GET /ready` is called, then the response is `200` with `{"status": "ready"}`; given the database is unreachable or does not answer, when `GET /ready` is called, then the response is `503` with `{"status": "not ready"}` within 1 second. (system AC-001.5)
- **AC-002.9** Given the database is unreachable, when `GET /health` is called, then the response is `200` with `{"status": "ok"}`, and the service process keeps running. (system AC-001.5)
- **AC-002.10** Given tasks were created and the database then became unreachable while the service kept running, when the database is reachable again, then without restarting the service the next `GET /ready` answers `200` `{"status": "ready"}` and the next `GET /tasks` answers `200` with all tasks created before the outage, in creation order. (system AC-001.5)
- **AC-002.11** Given the service is started while its database is unreachable and the database holds no tasks schema yet, when the service starts, then it starts and `GET /health` answers `200`; and when the database then becomes reachable, then without restarting the service `GET /ready` answers `200`, `POST /tasks` with a valid body answers `201` and `GET /tasks` lists that task. (system AC-001.5)
- **AC-002.12** Given an empty database and two instances of the service started at the same moment, when both have started, then both answer `GET /ready` with `200`, a task created through either instance is listed by both, and neither instance failed or restarted while setting up storage. (system AC-001.2)
- **AC-002.13** Given the connection setting `DATABASE_URL` points at a reachable database, when it uses the scheme `postgres://` or the scheme `postgresql://`, then in both cases the service answers `GET /ready` with `200` and `POST /tasks` with a valid body with `201`. (system AC-001.1)
- **AC-002.14** Given the connection setting `DATABASE_URL` is not set, when the service is started, then it does not start serving (`GET /health` is never answered), the process exits with a non-zero status, and its log contains a line naming `DATABASE_URL` as missing. (system AC-001.5)

## Non-goals

- Carrying over tasks held in memory by a running instance of the previous version: those are lost on the switch to the database.
- Database backups, restore and retention (a later system spec).
- Retrying a failed database call inside the API or queueing creates during an outage: the caller gets `503` and decides.
- Reading a single task, updating, completing or deleting tasks; filtering, searching or pagination; users or per-user lists; fields beyond `id`, `title` and `due_date` (unchanged from spec 001).
- A limit on how many tasks are stored.
- Showing database error details to callers: a `503` body is always `{"detail": "database unavailable"}`.
- Connection settings other than `DATABASE_URL` (the separate `PG*` variables are not read).

## Open questions

- ~~When `DATABASE_URL` is not set at all, should the service refuse to start, or start and behave as if the database were down?~~ Answered: refuse to start with a log line naming `DATABASE_URL`, see AC-002.14.

## Decisions taken during the ship

- When `DATABASE_URL` is not set, should the service refuse to start or start as if the database were down? Decided: it refuses to start, exiting non-zero with a log line naming `DATABASE_URL` (AC-002.14).

## Changelog

- 2026-11-06 created
- 2026-11-06 amended: answered the open question on a missing `DATABASE_URL` (refuse to start); added AC-002.14 and the section "Decisions taken during the ship".
- 2026-11-06 approved
- 2026-11-06 building
- 2026-11-06 done
