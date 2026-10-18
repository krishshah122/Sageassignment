# Live project status

Last updated: 2026-10-18

## Product and current scope

This repository is the Order Supervisor POC described in [sagedoc.txt](./sagedoc.txt). Its approved target stack and requirements are recorded in [proj.md](./proj.md) and [ARCHITECTURE.md](./ARCHITECTURE.md).

The current milestone is the backend persistence/API foundation. It is not yet an end-to-end submission.

## Implemented

- Environment-backed backend settings and the existing no-op Temporal workflow.
- SQLAlchemy models for supervisors, runs, timeline entries, run memory, and final output.
- FastAPI supervisor create/list/detail endpoints.
- FastAPI run create/list/detail endpoints. Run creation persists a row and starts an `OrderSupervisorWorkflow` whose workflow ID is the run UUID.
- Event injection for all nine assignment event types. Events are sent as Temporal signals and persisted by worker activities. `delivered` records the event, marks the run completed, and closes its workflow.
- Docker Compose API service on port 8000, alongside existing PostgreSQL and Temporal services.

## Incomplete

- Agent inference, Groq integration, wake classifier, and scheduled wakes.
- Mocked agent tools, memory compaction, and final output generation.
- Extra live-run instructions and interrupt/pause/resume/terminate endpoints.
- Next.js App Router/Tailwind UI.
- Database migrations, beyond `create_all` during API startup.
- A Docker-backed end-to-end run; Compose syntax was checked, but the services were not started.

## Files changed or added in this milestone

- `backend/app/db/`: SQLAlchemy models, engine/session dependency, schema initialization.
- `backend/app/api/`: supervisor/run routes and request/response schemas.
- `backend/app/main.py`: FastAPI application and startup schema initialization.
- `backend/app/temporal/`: durable per-run workflow, event persistence activities, worker registration and sync activity executor; existing no-op workflow remains.
- `backend/tests/test_api.py`: SQLite-backed API checks with Temporal calls mocked.
- `backend/tests/test_order_workflow.py`: Temporal signal/activity persistence and delivery completion check.
- `backend/requirements.txt`: FastAPI, SQLAlchemy, PostgreSQL driver, Uvicorn, and HTTP test client.
- `docker-compose.yml`, `README.md`, `ARCHITECTURE.md`: API service, run instructions, and implemented-state notes.

## Verification

- Python 3.12.5 backend suite: **8 passed**, 1 Starlette deprecation warning.
- `docker compose config --quiet`: passed.
- `git -c core.whitespace=cr-at-eol diff --check`: passed using the repository's existing CRLF line endings.
- No Docker containers were started, so PostgreSQL/Temporal integration in Compose remains unverified.

## Next step

Implement the wake/sleep decision path in `OrderSupervisorWorkflow`: retain signal-driven operation, add scheduled wake behavior and a policy classifier, then test important versus non-important events and timer wakes with Temporal's time-skipping environment. Agent/tool orchestration and run controls remain later work.
