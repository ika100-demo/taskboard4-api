---
spec_id: 001-create-and-list-tasks
title: Create and list tasks
status: draft
priority: P1
shape: service-python
---

# 001 — Create and list tasks

## Problem

The Task API has no tasks yet: it only answers health, readiness, ping and metrics. Callers (a future web front end, scripts, people trying out the service) have nowhere to record what needs doing or to see what they have recorded. This first feature lets them create a task with a title and an optional due date and list every task they have created. Tasks are kept in the service's memory only, so the feature can ship before any storage exists.

## Stories

As an API caller, I want to create a task with a title and, if I want, a due date, so that I have a record of what I need to do and by when.

As an API caller, I want to list all tasks, so that I can see everything recorded so far.

## Acceptance criteria

- **AC-001.1** Given the service is running, when a caller sends `POST /tasks` with the JSON body `{"title": "Buy milk"}`, then the response is `201` with a JSON object holding `id` (a non-empty string), `title` equal to `"Buy milk"` and `due_date` equal to `null`. (smoke)
- **AC-001.2** Given the service is running, when a caller sends `POST /tasks` with `{"title": "File taxes", "due_date": "2026-12-31"}`, then the response is `201` and its `due_date` is `"2026-12-31"`.
- **AC-001.3** Given two tasks are created one after another with the same title, when both responses arrive, then their `id` values differ.
- **AC-001.4** Given the service is running, when a caller sends `POST /tasks` with no `title`, with `title` set to `""`, with a title of only whitespace, or with a `title` that is not a string, then the response is `422`, the body names the field `title`, and no task is added to the list.
- **AC-001.5** Given the service is running, when a caller sends `POST /tasks` with a `title` longer than 200 characters, then the response is `422`, the body names the field `title`, and no task is added; a title of exactly 200 characters is accepted with `201`.
- **AC-001.6** Given the service is running, when a caller sends `POST /tasks` with a `due_date` that is not a calendar date in the form `YYYY-MM-DD` (for example `"2026-13-01"`, `"2026-02-30"`, `"tomorrow"` or `"2026-12-31T10:00:00Z"`), then the response is `422`, the body names the field `due_date`, and no task is added.
- **AC-001.7** Given the service is running, when a caller sends `POST /tasks` with a body that is not valid JSON, then the response is `422` and no task is added.
- **AC-001.8** Given no task has been created since the service started, when a caller sends `GET /tasks`, then the response is `200` with an empty JSON array `[]`.
- **AC-001.9** Given tasks "A", "B" and "C" were created in that order, when a caller sends `GET /tasks`, then the response is `200` with a JSON array of three objects in creation order, each with the same `id`, `title` and `due_date` as returned when it was created. (smoke)
- **AC-001.10** Given tasks were created, when the service restarts and a caller sends `GET /tasks`, then the response is `200` with an empty JSON array `[]` (tasks are kept in memory only).
- **AC-001.11** Given the service is running, when a caller sends `POST /tasks` with `{"title": "  Buy milk  "}`, then the response is `201` with `title` equal to `"Buy milk"`, and `GET /tasks` returns that task with `title` equal to `"Buy milk"`.
- **AC-001.12** Given today is after 2020-01-01, when a caller sends `POST /tasks` with `{"title": "Overdue", "due_date": "2020-01-01"}`, then the response is `201` with `due_date` equal to `"2020-01-01"`.

## Non-goals

- Persisting tasks across restarts or sharing them between several running instances of the service.
- Reading a single task, updating, completing or deleting tasks.
- Filtering, sorting options, searching or paginating the list.
- Users, authentication or per-user task lists: every caller sees every task.
- Due times or time zones: a due date is a calendar date only.
- A limit on how many tasks the service keeps in memory.
- Any fields beyond `id`, `title` and `due_date` (description, priority, status, tags).

## Open questions

- ~~Should a due date in the past be accepted?~~ Answered: yes, stored as given, see AC-001.12.
- ~~Should the service cap how many tasks it keeps in memory?~~ Answered: no cap in this spec, see Non-goals.
- ~~Confirm: the maximum title length is 200 characters.~~ Answered: 200, see AC-001.5.
- ~~Confirm: leading and trailing whitespace in a title is trimmed.~~ Answered: trimmed before storing and returning; an all-whitespace title is rejected, see AC-001.4 and AC-001.11.
- ~~Confirm: invalid input answers `422` with a body naming the offending field.~~ Answered: yes, see AC-001.4 to AC-001.7.
- ~~Confirm: `GET /tasks` returns a bare JSON array in creation order.~~ Answered: bare array, oldest first, see AC-001.8 and AC-001.9.
- ~~Confirm: paths `POST /tasks` and `GET /tasks`, fields `id`, `title`, `due_date`.~~ Answered: yes, snake_case, used in all criteria.

## Changelog

- 2026-11-06 created
- 2026-11-06 amended: answered all open questions; added AC-001.11 (title trimming) and AC-001.12 (past due dates accepted); task cap moved to Non-goals.
