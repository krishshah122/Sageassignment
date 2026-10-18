# Order Supervisor

POC for a long-running Temporal AI supervisor per order. See [sagedoc.txt](sagedoc.txt), [proj.md](proj.md), and [ARCHITECTURE.md](ARCHITECTURE.md).

## Milestone 1 (current)

Local Postgres + Temporal, plus a Python worker that can complete a no-op workflow. No HTTP API, UI, or LLM yet.

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

The `worker` service polls task queue `order-supervisor` and registers `NoopWorkflow`.

### Tests (no Docker required)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pytest
```
