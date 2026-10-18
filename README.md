# Order Supervisor

POC for a long-running Temporal AI supervisor per order. See [sagedoc.txt](sagedoc.txt), [proj.md](proj.md), and [ARCHITECTURE.md](ARCHITECTURE.md).

## Current milestone

Local Postgres + Temporal, a Python worker, and a FastAPI persistence/API foundation. Supervisors can be created and inspected; runs start a durable per-run Temporal workflow and accept lifecycle events. A `delivered` event marks a run completed.

Agent inference, wake classification, scheduled wake-ups, mocked agent tools, run controls, memory/final output generation, and the Next.js UI are not implemented yet.

### Prerequisites

- Docker Desktop
- Python 3.12 (for running tests on the host)

### Run infrastructure and worker

```bash
cp .env.example .env
docker compose up --build
```

- Temporal gRPC: `localhost:7233`
- Temporal UI: `http://localhost:8080`
- Postgres: `localhost:5432` database `order_supervisor` (user/password `postgres` — local demo only)
- FastAPI: `http://localhost:8000` (interactive API docs: `http://localhost:8000/docs`)

The `worker` service polls task queue `order-supervisor` and registers `NoopWorkflow` and `OrderSupervisorWorkflow`. The API creates the PostgreSQL schema on startup; migrations are not configured yet.

### Implemented API

- `POST /api/supervisors`, `GET /api/supervisors`, `GET /api/supervisors/{id}`
- `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/events` accepts the assignment event types. Events are delivered as workflow signals and persisted in the timeline. `delivered` completes the basic workflow.

### Tests (no Docker required)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pytest
```
