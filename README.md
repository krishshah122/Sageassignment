# Order Supervisor

POC for a long-running Temporal AI supervisor per order. See [sagedoc.txt](sagedoc.txt), [proj.md](proj.md), and [ARCHITECTURE.md](ARCHITECTURE.md).

For the complete setup, synthetic walkthrough, expected results, and troubleshooting steps, see [help.md](help.md).

For a detailed explanation of orders, Temporal workflows, the worker, the AI agent, and simulated tools, see [worker-and-order.md](worker-and-order.md).

## Current milestone

The backend runs a Groq-backed agent on workflow start, important order events, and scheduled wakes. The agent can update compact run memory and execute simulated tools; outcomes, errors, and final summaries are stored in the run timeline/database.

The operator console supports supervisor setup, run creation/monitoring, event and instruction injection, and run controls. Live-run instructions and pause/resume/interrupt/terminate controls are implemented in the backend.

### Prerequisites

- Docker Desktop
- Python 3.12 (for running tests on the host; tests also pass on Python 3.10)
- A Groq API key for live agent inference

### Run infrastructure and worker

Create or edit `.env` in the repository root and set `GROQ_API_KEY` to your Groq key. The default model is `openai/gpt-oss-20b`; set `GROQ_MODEL` in `.env` to override it. Keep `.env` private and do not commit it.

On Windows PowerShell, disable Compose Bake for this first build to avoid a Docker Desktop image-export collision when the API and worker build from the same backend Dockerfile:

```powershell
$env:COMPOSE_BAKE = "false"
docker compose up --build
```

On other shells, `docker compose up --build` is sufficient. Keep the terminal running while using the app; press `Ctrl+C` to stop the services.

- Temporal gRPC: `localhost:7233`
- Temporal UI: `http://localhost:8080`
- Postgres: `localhost:5432` database `order_supervisor` (user/password `postgres` — local demo only)
- FastAPI: `http://localhost:8000` (interactive API docs: `http://localhost:8000/docs`)
- Operator console: `http://localhost:3000`

The `worker` service polls task queue `order-supervisor` and registers `NoopWorkflow` and `OrderSupervisorWorkflow`. The API creates the PostgreSQL schema on startup; migrations are not configured yet.
Set `GROQ_API_KEY` in `.env` before starting. The key is passed to the worker only and is never sent to the browser or API container. `GROQ_MODEL` defaults to `openai/gpt-oss-20b` and can be changed in `.env`. The LLM receives order context, recent timeline, memory, and new events; its response must be valid JSON matching the agent decision schema. Missing keys, provider errors, and invalid responses are recorded in the timeline and retried on the next wake rather than silently replaced with fake AI output.
Order context, event payloads, timeline entries, and supervisor/run instructions are sent to Groq for inference; do not include secrets or data you are not permitted to share with that service.

Runs use the supervisor's optional default wake-up interval, or `DEFAULT_WAKEUP_SECONDS` (30 by default). Payment failures, shipment delays, refund requests, and customer messages invoke the agent immediately; routine events are recorded without resetting the timer. Timer wakes invoke the agent, too.

The supervisor can enable only three simulated tools: customer message, internal note, and mark for human review. They only record simulated results; they do not contact real systems. Timer scheduling is controlled by the agent's `next_wakeup_seconds` decision field, not an extra tool. A delivered event starts finalization.

### Agent and system evaluation

The normal backend suite checks request validation, mocked tool behavior, API controls, Temporal signals/timers, and the complete synthetic workflow using a fake model response. To score real Groq responses against the synthetic references with RAGAS, add `RAGAS_MODEL=groq/openai/gpt-oss-20b` to the private root `.env` if using another evaluator model, then run:

```powershell
docker compose --profile evaluation run --build --rm ragas-eval
```

This optional evaluation calls Groq for three synthetic agent scenarios and makes additional Groq calls for RAGAS judging. It reports factual correctness, faithfulness (grounding in supplied evidence), response relevance, and instruction adherence. It is not part of startup or ordinary tests and may consume API quota. Timestamped JSON and CSV scores are written under `backend/evals/results/` and are git-ignored. Use synthetic data only. These scores evaluate agent responses; the existing automated integration tests verify end-to-end workflow mechanics.

### Implemented API

- `POST /api/supervisors`, `GET /api/supervisors`, `GET /api/supervisors/{id}`
- `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/events` accepts the assignment event types. Events are delivered as workflow signals and persisted in the timeline. `delivered` triggers agent finalization and completes the workflow after final output is persisted.
- `POST /api/runs/{run_id}/instructions` appends an instruction to the run context for the next agent invocation.
- `POST /api/runs/{run_id}/pause`, `/resume`, and `/interrupt` control workflow wakes. Events continue to be recorded while paused; pending urgent events and interrupts run after resume. An already-running agent activity is allowed to finish before pause takes effect.
- `POST /api/runs/{run_id}/terminate` terminates the Temporal workflow without generating final output.

### Run the UI outside Docker

```bash
cd web
npm ci
npm run dev
```

The Next.js server proxies `/api/*` to `API_URL`, which defaults to `http://localhost:8000` for local development. The UI is configured with `http://api:8000` inside Compose and does not receive the Groq key.

### Tests (no Docker required)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pytest
```

The test suite uses a fake Groq response and Temporal's time-skipping test environment. It does not need a Groq key or Docker.
