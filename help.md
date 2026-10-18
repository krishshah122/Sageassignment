# Order Supervisor POC: Run and Test Guide

This guide covers the local Docker demo from first startup through a complete synthetic order run. Use synthetic data only.

For a plain-language explanation of what an order, workflow, worker, agent, and mocked tool mean in this project, see [worker-and-order.md](worker-and-order.md).

## What the app does

1. The Next.js operator console sends supervisor and order requests to FastAPI.
2. FastAPI stores supervisors, runs, events, agent memory, and final output in PostgreSQL.
3. Temporal keeps each order workflow alive, waiting for an important event or its next scheduled wake.
4. The Temporal worker sends the supervisor instructions, order context, recent timeline, memory, and triggering events to Groq with the agent decision JSON Schema. The worker validates the response locally, updates memory, and records the result.
5. Any enabled tools are local simulations. They do not send customer messages, change orders, or contact commerce systems.

The Groq request includes the order context and event content. Do not use real customer details, credentials, payment information, or other data you are not allowed to send to Groq.

## URLs

| Service | URL | Purpose |
| --- | --- | --- |
| Operator console | <http://localhost:3000> | Create supervisors and runs; inject events and instructions; inspect run status, timeline, memory, and final output. |
| FastAPI | <http://localhost:8000> | Backend API. |
| API documentation | <http://localhost:8000/docs> | Browse and call the HTTP endpoints. |
| Temporal UI | <http://localhost:8080> | Inspect Temporal workflows and their execution history. |
| Temporal gRPC | `localhost:7233` | Internal workflow client connection; not a browser page. |
| PostgreSQL | `localhost:5432` | Local demo database; normally use the application rather than connecting directly. |

## Prerequisites and Groq configuration

- Docker Desktop must be running.
- A Groq API key is needed for real agent runs. The automated tests use a fake provider and do not need the key.
- The configured default model is `openai/gpt-oss-20b`. It is a smaller model suitable for cost-conscious testing, but account access, rate limits, and free-tier quotas are controlled by Groq and can change. Check the Groq Console for your account's current limits; do not assume inference is unlimited or free.

In the repository root, create or edit `.env` and set the key and model. On Windows, `notepad .env` opens the file:

```dotenv
GROQ_API_KEY=replace_with_your_groq_key
GROQ_MODEL=openai/gpt-oss-20b
```

Keep any existing settings in `.env`; replace the example key with your own. The file is git-ignored. Never paste the key into the UI, source code, screenshots, or chat. Compose passes the key to the worker only, not the API or browser.

If you change `.env` while containers are already running, recreate the worker so it receives the new environment:

```powershell
docker compose up -d --force-recreate worker
```

## Start and stop the app

Open PowerShell in the repository root. On Windows, disable Compose Bake for the initial build; this avoids the image-export collision seen when the API and worker build from the same Dockerfile:

```powershell
$env:COMPOSE_BAKE = "false"
docker compose up --build
```

Leave this terminal open while using the app. When Compose reports the services are running, open <http://localhost:3000>. The dashboard refreshes automatically and should report that the API is connected.

Useful commands from a second PowerShell window in the repository root:

```powershell
docker compose ps
docker compose logs -f api worker
docker compose exec -T api pytest -q /srv/tests
```

Press `Ctrl+C` in the attached `docker compose up` terminal to stop it, or run:

```powershell
docker compose down
```

`docker compose down` keeps the PostgreSQL data volume. Do not add `-v` unless you intentionally want to delete the local database and its saved runs.

## Run a complete synthetic order

### 1. Create a supervisor

In the operator console, use **Create a supervisor**:

- **Supervisor name:** `Demo order supervisor`
- **Base instruction:** `Monitor this synthetic order. Summarize facts accurately. Do not claim real-world actions. When the delivered event arrives, provide complete final output.`
- **Available simulated tools:** choose only from customer message, internal note, and mark for human review. All three only record simulated results.
- **Wake interval:** use `3600` seconds during a short demo so the timer does not trigger repeated paid inference.
- **Model override:** leave blank to use `GROQ_MODEL` from `.env`.

Select **Save supervisor**. It should appear in the Supervisor selector in the new-run form.

### 2. Start a run

Use **Start an order run**:

- **Supervisor:** select `Demo order supervisor`.
- **Order ID:** `TEST-1001`.
- **Order context (JSON):**

```json
{
  "status": "in_transit",
  "items": ["synthetic ceramic mug"],
  "shipping": {
    "carrier": "Example Parcel",
    "tracking_status": "in_transit"
  },
  "customer_request": "Please confirm whether the package has arrived."
}
```

Select **Start order run**. The workflow starts an agent run immediately. After a valid Groq response, expect an `agent_run` timeline entry, an updated memory summary, and a run that is generally `sleeping` until the next event or timer. Status changes can take a few seconds because the UI refreshes periodically.

### 3. Send a delivered event to finalize

In the selected run's event form, choose event type `delivered` and enter this JSON payload:

```json
{
  "source": "synthetic demo",
  "note": "Package delivered for test purposes."
}
```

Submit the event. A delivered event asks the agent to finalize. On success, the run becomes `completed`, the timeline includes the event and final agent run, and the **Final output** panel shows a summary, important actions, learnings, and feedback. Final output is only created by a successful finalization; terminating a run does not create it.

### Optional: test an urgent event and a simulated tool

To test another inference trigger, create a separate run, then send event type `shipment_delayed` with:

```json
{
  "reason": "Synthetic weather delay",
  "source": "demo"
}
```

Payment failures, shipment delays, refund requests, and customer messages are urgent wake triggers. If the supervisor has `create_internal_note` enabled, the model may choose that action; its result will be marked simulated in the timeline. The model chooses whether an action is appropriate, so a tool checkbox does not guarantee that the model will call it.

Other accepted event types are `order_created`, `payment_confirmed`, `payment_failed`, `shipment_created`, `shipment_delayed`, `delivered`, `refund_requested`, `customer_message_received`, and `no_update_for_n_hours`. Event payloads must be JSON objects. Use synthetic values.

## Optional: score Groq agent quality with RAGAS

The optional RAGAS evaluation runs three synthetic cases through the real Groq agent, then judges the returned decisions for factual correctness against expected references, faithfulness to the supplied order evidence, response relevance, and instruction/tool compliance.

From the repository root, with a private `.env` containing `GROQ_API_KEY`, run:

```powershell
docker compose --profile evaluation run --build --rm ragas-eval
```

This makes additional provider calls for evaluation; it may consume Groq quota. The JSON summary and per-case CSV are saved to `backend/evals/results/` (ignored by Git). RAGAS scores are a small-sample diagnostic, not proof of general accuracy. Regular backend tests use a fake model and verify the API, mock tools, and Temporal sleep/signal/wake/finalization path without provider cost.

## What the controls do

- **Add instruction:** saves extra run-specific guidance for the next agent invocation; it does not itself trigger an inference.
- **Pause:** defers agent calls while still allowing incoming events to be recorded.
- **Resume:** allows deferred urgent events and interrupts to be processed.
- **Interrupt:** requests an agent wake.
- **Terminate:** permanently stops the Temporal workflow and does not produce final output.

## API endpoints

The interactive API reference is at <http://localhost:8000/docs>. Main routes:

- `POST /api/supervisors`, `GET /api/supervisors`, `GET /api/supervisors/{supervisor_id}`
- `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/events`
- `POST /api/runs/{run_id}/instructions`
- `POST /api/runs/{run_id}/pause`, `/resume`, `/interrupt`, and `/terminate`

The run detail endpoint includes status, timeline entries, memory, and final output. The API does not expose a separate `/health` route; use `/docs` or the dashboard's API connection indicator to check that the API is reachable.

## Automated tests

With the Docker services running, execute the backend suite inside the API container:

```powershell
docker compose exec -T api pytest -q /srv/tests
```

These tests use fake Groq responses, SQLite, and Temporal's time-skipping test environment. They are designed to run without a Groq key or live provider calls. A real workflow walkthrough does use Groq inference and may consume account quota.

## Troubleshooting

### Dashboard says the API is unavailable

Check `docker compose ps`. If `api` is not running, inspect `docker compose logs --tail 100 api`. Confirm <http://localhost:8000/docs> opens. A request to `/health` returns 404 because no health route is currently defined.

### Worker says the Groq key is missing

Check that `GROQ_API_KEY` is set in the root `.env`, then run `docker compose up -d --force-recreate worker`. Do not print the key in logs or commands when troubleshooting.

### Groq returns an error or the run records `agent_error`

Inspect `docker compose logs --tail 100 worker` and the run timeline. Confirm the selected model is available to your Groq account, the key is active, and your account has quota remaining. HTTP 429/rate-limit responses are controlled by Groq. Use fewer event tests and a longer wake interval to reduce requests. The request includes the decision JSON Schema and the worker validates the response locally; invalid model output is rejected rather than silently treated as a successful decision.

### Worker reports a PostgreSQL driver import error

The API and worker must use the `postgresql` SQLAlchemy URL scheme with the installed `psycopg2-binary` package. Rebuild/recreate both backend containers after changing code or Compose configuration:

```powershell
$env:COMPOSE_BAKE = "false"
docker compose up -d --build api worker
```

### A run is sleeping

`sleeping` is the expected state while Temporal waits for an event or the configured wake interval. Send an urgent event or use **Interrupt** to request an earlier agent run. Send `delivered` to ask for final output.

## Scope and safety reminders

- This is a local proof of concept, not a production order-management system.
- Mock tools only record simulated outcomes; they do not send messages or modify external orders.
- PostgreSQL data is local to the Docker volume. There are no configured migrations yet.
- Use test-only orders and avoid putting secrets or personal data into order context, events, or instructions.
