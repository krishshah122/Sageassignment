# Order Supervisor — POC architecture

Implemented architecture for the POC in [sagedoc.txt](sagedoc.txt) and [proj.md](proj.md). The goal is the smallest maintainable system that meets the assignment's core requirements.

**Chosen scope:** local Docker Compose (Temporal, PostgreSQL, FastAPI, Next.js); Groq API with account-dependent quotas; no authentication; mocked tools.

---

## 1. Major components and responsibilities

Four processes, one database. No extra microservices, Redis, or message buses. Temporal is required by the assignment (long-running workflow + signals + timers), not an extra queue.

| Component | Responsibility | Boundary |
| --- | --- | --- |
| **web** (Next.js App Router + Tailwind) | Operator UI: supervisors, run list/detail, event injector, extra instructions, pause/resume/interrupt/terminate. No business logic beyond HTTP calls and rendering. | Talks only to FastAPI `/api/*`. |
| **api** (FastAPI) | HTTP for supervisors and runs. Persist reads/writes to PostgreSQL. Start workflows and send signals/control via Temporal client. | Does not call Groq. Does not run agent loops. |
| **worker** (Temporal Python worker) | Hosts `OrderSupervisorWorkflow` and activities. Durable sleep/wake, deterministic event wake policy, agent, tools, memory update, and finalization. | Activities talk to Postgres and Groq. Workflow code stays deterministic (no I/O). |
| **postgres** | Source of truth for supervisors, runs, timeline, memory, actions, final output. | Accessed by **api** and **worker** activities only. |
| **temporal** | Durable workflow state, signals, timers. | Used by **api** (client) and **worker**. |

### Module boundaries (backend)

```
backend/app/
  config.py          # env-backed settings
  db/                # SQLAlchemy models + session
  api/               # FastAPI routers (HTTP contracts)
  temporal/          # workflow, activities, worker entry
  agent/             # Groq client, tool implementations, prompt assembly and decision schemas
```

Interfaces:

- HTTP: Pydantic request/response models in `api/`.
- Temporal: workflow signals (`event`, `interrupt`, `pause`, `resume`) and activity function signatures. Run-specific instructions are persisted by the API and read by the next agent activity.
- Persistence: SQLAlchemy sessions used directly by API handlers and activities (plain functions, not a DDD layer).

The agent module is callable only from Temporal activities so inference cannot run in a tight API loop.

---

## 2. Data flow

```
Operator → Next.js → FastAPI → PostgreSQL
                              ↘ Temporal Client (start / signal / terminate)
Temporal Worker ← timers/signals ← Temporal server
     │
     ├─ wake_policy (deterministic event policy; no extra LLM call)
     ├─ run_agent (Groq + mocked tools)
     ├─ persist timeline / memory / status (Postgres)
     └─ maybe schedule next wake (workflow timer)
```

Typical run:

1. Operator creates supervisor → row in `supervisors`.
2. Operator starts a run → FastAPI inserts `runs` (`status=starting`) → `client.start_workflow(workflow_id=run_id)` → workflow runs start trigger → `run_agent` activity → persist timeline/memory → workflow `wait_condition` on signal **or** timer.
3. Operator injects event → FastAPI signals the workflow → worker activity persists the event → deterministic wake policy decides whether to wake the agent immediately or stay asleep.
4. Extra instruction → append to the run's durable context and timeline; the next agent invocation reads it. Adding instructions does not force an immediate wake.
5. Pause → signal `pause`; the workflow records events but defers new inference while paused. An already-running agent activity is allowed to finish. Resume restores pending urgent events/interrupts; an elapsed timer can also wake immediately after resume.
6. Interrupt → signal `interrupt`; the main agent runs immediately when not paused, or after resume if paused.
7. Terminal (`delivered` or operator terminate) → final agent step on delivery (hard terminate skips it) → terminal status → workflow return.

---

## 3. Database schema and relationships

PostgreSQL. UUIDs as text/uuid. JSON columns for small nested blobs (order context, tool args). No extra tables for analytics.

```
supervisors 1──* runs 1──* timeline_entries
                   │
                   ├── 1──1 run_memories     (compact summary; 1 row per run)
                   └── 1──1 run_final_outputs (nullable until complete)
```

Actions are timeline entries with `kind=action` (one table). Events are `kind=event`. Agent notes/errors are `kind=system`. This avoids a second history table.

### supervisors

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| name | text not null | |
| base_instruction | text not null | |
| available_tools | jsonb not null | list of tool name strings |
| default_wakeup_seconds | int null | optional |
| model | text null | optional Groq model override |
| wake_aggressiveness | text null | e.g. `low` / `normal` / `high` |
| created_at | timestamptz | |

### runs

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | **Assumption:** equals Temporal workflow_id |
| supervisor_id | uuid fk | |
| order_id | text not null | opaque order identifier from UI |
| order_context | jsonb not null | free-form order fields |
| extra_instructions | jsonb not null | list of strings, default `[]` |
| status | text not null | `running` / `paused` / `sleeping` / `completed` / `terminated` / `failed` |
| sleep_until | timestamptz null | next scheduled wake |
| temporal_workflow_id | text not null | same as id unless we later split |
| created_at, updated_at | timestamptz | |

### timeline_entries

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid pk | |
| run_id | uuid fk | |
| kind | text | `event` / `action` / `system` |
| type | text | event type or tool name |
| payload | jsonb | |
| created_at | timestamptz | |

### run_memories

| Column | Type | Notes |
| --- | --- | --- |
| run_id | uuid pk fk | |
| summary | text not null | rolling compact summary |
| updated_at | timestamptz | |

### run_final_outputs

| Column | Type | Notes |
| --- | --- | --- |
| run_id | uuid pk fk | |
| summary | text | |
| important_actions | jsonb | |
| learnings | text | |
| feedback | text | |
| created_at | timestamptz | |

Indexes: `runs(status)`, `timeline_entries(run_id, created_at)`.

Terminal **assumption:** `completed` after close/delivered + final output; `terminated` after operator terminate.

---

## 4. API contracts (frontend ↔ backend)

JSON, prefix `/api`. Assignment suggested paths plus pause.

Error shape: `{ "detail": string }` (FastAPI default). `404` unknown id, `400` validation, `409` illegal control on terminal run.

### Supervisors

`POST /api/supervisors`

```json
{
  "name": "Default order supervisor",
  "base_instruction": "Watch this order. Act only when needed.",
  "available_tools": [
    "send_customer_message",
    "create_internal_note",
    "mark_order_for_review"
  ],
  "default_wakeup_seconds": 60,
  "model": null,
  "wake_aggressiveness": "normal"
}
```

Response `201`: supervisor object including `id`.

`GET /api/supervisors/{id}` → `200` supervisor object.

**Assumption (needed for UI list):** `GET /api/supervisors` returns `{ "items": [ ... ] }`. Assignment listed only GET-by-id; list is required to pick a template.

### Runs

`POST /api/runs`

```json
{
  "supervisor_id": "<uuid>",
  "order_id": "ORD-1001",
  "order_context": { "customer": "Ada", "items": ["SKU-1"] }
}
```

Response `201`: run summary (id, status, supervisor_id, order_id).

`GET /api/runs` → `{ "items": [ run summaries ] }` (active and completed).

`GET /api/runs/{run_id}` → full run:

```json
{
  "id": "...",
  "supervisor_id": "...",
  "order_id": "ORD-1001",
  "order_context": {},
  "extra_instructions": ["If shipment is delayed, escalate immediately."],
  "status": "sleeping",
  "sleep_until": "2026-10-18T05:00:00Z",
  "memory_summary": "...",
  "timeline": [ { "kind": "event", "type": "payment_confirmed", "payload": {}, "created_at": "..." } ],
  "final_output": null
}
```

`POST /api/runs/{run_id}/events`

```json
{ "type": "shipment_delayed", "payload": { "reason": "weather" } }
```

Allowed `type` values: the FR-10 list. Unknown types: `400` (or accept as `unknown` if FR-19 is implemented later).

`POST /api/runs/{run_id}/instructions`

```json
{ "text": "Do not contact the customer without human review." }
```

Control: `POST .../pause|resume|interrupt|terminate` with empty body `{}`. Response: updated run summary.

The Next.js server rewrites `/api/*` to `API_URL`, keeping API traffic same-origin from the browser. Local development defaults to `http://localhost:8000`; Compose sets `http://api:8000`. The Groq key is not exposed to the web container.

---

## 5. Authentication and authorization

Assignment: do not build authentication.

Boundary: every HTTP route is open on the local network. No roles, JWT, or RLS.

**Assumption:** bind API to localhost in Docker for the demo. Do not expose Groq key to the browser (server-side worker only).

If auth is added later, wrap FastAPI dependencies; workflow internals stay unchanged.

---

## 6. External integrations and failure handling

| Integration | Use | Failure handling |
| --- | --- | --- |
| **Temporal** | Workflow, signals, timers | Required. Worker crash: workflow continues after restart. API start/signal errors return 503/502 with detail. |
| **PostgreSQL** | Persistence | API: fail the request. Activities: Temporal retries with timeout; after retries, write `kind=system` error on timeline and keep workflow alive. |
| **Groq** | Main agent only | Activity timeout + limited retries. On failure: persist error, sleep until next timer/signal, do not kill workflow. No fallback paid LLM. |
| **Mocked tools** | Side effects simulated in-process | Exactly three allowed tools: customer message, internal note, and mark for human review. Validate arguments and persist each result as a timeline action. |
| **RAGAS evaluation** | Optional separate Compose profile | Runs three synthetic agent scenarios and scores factual correctness, faithfulness, response relevance, and instruction adherence. Not installed in or required by the API/worker runtime. |

No real Stripe/email/shipping. Event wake policy is deterministic and in-process, so routine event decisions do not consume Groq quota.

---

## 7. Configuration and secrets

Single root `.env` (git-ignored). A `.env.example` file is not currently present; follow [help.md](help.md) to create/edit `.env`.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres |
| `TEMPORAL_ADDRESS` | e.g. `temporal:7233` |
| `TEMPORAL_NAMESPACE` | `default` |
| `TEMPORAL_TASK_QUEUE` | `order-supervisor` |
| `GROQ_API_KEY` | secret |
| `GROQ_MODEL` | free-tier model id chosen at implement time |
| `DEFAULT_WAKEUP_SECONDS` | short demo timer (e.g. 30) |
| `API_URL` | Next.js server-side API rewrite target; defaults to `http://localhost:8000` outside Compose |

Secrets: Groq key only. Never send it to Next.js. Docker Compose `env_file`.

---

## 8. Testing strategy

Keep tests cheap and aligned to AC-01–AC-09.

1. **Unit:** deterministic wake policy; Pydantic validation for event and tool payloads.
2. **Workflow (temporalio testing):** time-skipping worker — start run, send signal, assert agent activity count; sleep until timer; extra instruction in later prompt payload; pause skips agent; terminate.
3. **API:** TestClient — create supervisor/run, inject event (signal mocked or test Temporal env), 404 unknown run.
4. **UI:** Browser smoke test and manual walkthrough for AC-07/AC-08; there is no automated browser E2E suite.
5. **Do not** require load tests or multi-tenant tests.

---

## 9. Deployment architecture

Local demo only (assignment POC).

```
docker-compose.yml
  postgres
  temporal + temporal-ui
  api          # uvicorn FastAPI
  worker       # python -m app.temporal.worker
  web          # next start / next dev
```

Operator opens `http://localhost:3000`. Temporal UI optional on `8080`.

No Kubernetes, no CDN, no separate staging. Set `GROQ_API_KEY` in `.env`, then follow the Windows-aware start instructions in [help.md](help.md).

---

## 10. Trade-offs and why this fits the assignment

- **Monolith backend, two processes (api + worker):** needed because Temporal workers must be long-lived; still one codebase.
- **Temporal instead of `asyncio.sleep` in FastAPI:** required; this is the evaluation core.
- **Postgres as UI source of truth, Temporal as control plane:** UI can read history without querying workflow queries for every field. Slight dual-write risk; activities write DB after decisions so the demo stays inspectable if Temporal UI is unused.
- **Policy classifier, not a second agent:** assignment says simple is acceptable; saves Groq quota and latency.
- **One timeline table:** enough for FR-07; skip event/action split.
- **No auth, cache, or extra queue:** out of scope or unused.
- **Mocked tools:** required-not-real integrations.
- **Short timers:** walkthrough can show sleep/wake in minutes, not hours.

This is appropriate because evaluators asked for system design, Temporal usage, agent orchestration, and a small working end-to-end product—not a production platform.

---

## Current directory structure

```
sageAssignment/
  sagedoc.txt
  proj.md
  ARCHITECTURE.md
  PROMPTS.md
  README.md
  help.md
  live.md
  docker-compose.yml
  backend/
    requirements.txt
    app/
      main.py
      config.py
      db/
      api/
      agent/
      temporal/
    tests/
  web/
    package.json
    src/app/
    src/lib/
```

No shared package, no Nx, no extra apps.

## Verification and manual walkthrough

- Backend suite (with Docker running): `docker compose exec -T api pytest -q /srv/tests`.
- Compose validation: `docker compose config --quiet`.
- Full live demonstration: create a supervisor, start a synthetic run, wait for the start inference and memory, send `delivered`, and verify `completed` plus final output in the UI.
- Detailed inputs, expected outcomes, URLs, and troubleshooting: [help.md](help.md).
- Current verification results and remaining POC scope: [live.md](live.md).

---

## Reversible vs expensive decisions

**Cheap to change later**

- Groq model id and whether classifier uses LLM.
- Timer defaults and wake-aggressiveness mapping.
- Next.js rewrite vs `NEXT_PUBLIC_API_URL`.
- Extra instruction: wake immediately vs wait.
- Adding `GET /api/supervisors`.
- Tool payload shapes (mocked).
- Tailwind layout.

**Expensive to change later**

- Temporal as the run orchestrator (assignment-locked; switching to in-process jobs would rewrite the core).
- One workflow per order / `run_id` as workflow_id.
- PostgreSQL as the inspectable store (UI and activities depend on it).
- Python worker + FastAPI split vs embedding the worker in the API process (possible but messier in Compose).
- Timeline-as-single-table if you later need strict event/action schemas.
- No `continue_as_new` until histories get huge (adding it later is optional FR-20, moderate cost).

**Locked by the assignment (do not “redesign away”)**

- Next.js App Router, Tailwind, FastAPI, Temporal Python SDK, PostgreSQL.
- Signal-driven events, three inference triggers, mocked tools, no auth.

---

## Current implementation and verification

- FastAPI provides supervisor create/list/detail, run create/list/detail, instruction, event, and run-control endpoints.
- SQLAlchemy models cover supervisors, runs, timeline entries, run memory, and final output. PostgreSQL tables are created when the API starts; schema migrations are not configured.
- Creating a run starts `OrderSupervisorWorkflow` using the run UUID as its Temporal workflow ID.
- Event injection signals the workflow. The worker persists event entries; payment failures, shipment delays, refund requests, and customer messages invoke the agent immediately, while routine events leave the scheduled wake unchanged.
- The workflow invokes one Groq-backed agent activity on start, important event, and timer wake. It passes memory and recent timeline context, requests JSON Schema output, validates the decision locally, and persists updated memory and tool results.
- Six local mocked tools handle customer message, internal note, escalation, review flag, schedule wake-up, and close workflow. They never call external commerce or messaging systems.
- The workflow schedules durable Temporal timers using a supervisor's wake interval or `DEFAULT_WAKEUP_SECONDS`; sleep state, wake times, and trigger causes are persisted.
- Run-specific instructions are persisted and included in the next agent context. Pause defers inference while continuing to persist incoming events; resume releases pending urgent events or interrupts. Terminate hard-stops the Temporal workflow without finalization.
- A delivered event or close-workflow tool causes final output (summary, actions, learnings, and feedback) to be persisted.
- Provider, missing-key, and invalid-response failures are recorded after bounded activity retries; the workflow stays open and can retry on a later wake.
- The `NoopWorkflow` remains registered as a Temporal wiring check.

The API key is passed only to the worker using `GROQ_API_KEY`; the configurable model defaults to `openai/gpt-oss-20b`. Groq structured output uses best-effort schema mode and is still validated locally; provider errors or schema violations can fail an invocation and are surfaced in the timeline/logs.

The backend suite passes in the API container (**27 passed**, one Starlette deprecation warning). A live synthetic order has completed the start → delivered event → final output path through PostgreSQL, Temporal, the worker, and Groq. The operator console has been smoke-tested against the running services. The reproducible walkthrough is in [help.md](help.md); current verification notes and remaining scope are in [live.md](live.md).

### POC scope intentionally not implemented

- Real commerce, customer messaging, or carrier integrations; all tools are simulations.
- Authentication, multi-tenant controls, production deployment hardening, and database migrations.
- Optional assignment improvements: unknown-event escalation, Temporal `continue_as_new`, advanced memory compaction, supervisor templates, and analytics.
- A walkthrough video, which remains a submission/demonstration deliverable rather than application code.
