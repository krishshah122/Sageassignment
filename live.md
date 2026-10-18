# Live project status

Last updated: 2026-10-18

## Product and current scope

This repository is the Order Supervisor POC described in [sagedoc.txt](./sagedoc.txt). Its approved target stack and requirements are recorded in [proj.md](./proj.md) and [ARCHITECTURE.md](./ARCHITECTURE.md).

The completed milestones are the backend persistence/API foundation, deterministic wake/sleep orchestration, Groq-backed agent/tool execution, backend run controls, and the Next.js operator console. This is not yet an end-to-end submission.

## Implemented

- Environment-backed backend settings and the existing no-op Temporal workflow.
- SQLAlchemy models for supervisors, runs, timeline entries, run memory, and final output.
- FastAPI supervisor create/list/detail endpoints.
- FastAPI run create/list/detail endpoints. Run creation persists a row and starts an `OrderSupervisorWorkflow` whose workflow ID is the run UUID.
- Event injection for all nine assignment event types. Events are sent as Temporal signals and persisted by worker activities. `delivered` requests agent finalization; the workflow completes after final output is stored.
- A deterministic wake policy that immediately requests a wake for payment failures, shipment delays, refund requests, and customer messages. Other event types are persisted without changing the scheduled wake.
- Durable Temporal timer wake requests. Runs record the initial start trigger, important-event triggers, next wake time, and scheduled triggers in run state/timeline. Supervisor wake interval overrides `DEFAULT_WAKEUP_SECONDS` (30-second default).
- Groq chat-completions adapter using validated JSON output. The model is configurable and defaults to `openai/gpt-oss-20b`. The API key is injected only into the worker container.
- Agent execution on start, urgent event, scheduled timer, and finalization triggers. Prompt context includes base/run instructions, order context, recent timeline, memory, and triggering events.
- Six schema-validated mocked tools: send customer message, create internal note, escalate issue, mark for review, schedule next wake, and close workflow. These tools make no real external calls.
- Agent summaries, tool action results/failures, updated compact memory, LLM errors, and final summary/actions/learnings/feedback are stored in the existing tables.
- Provider, missing-key, and malformed-response errors use bounded Temporal activity retries and are recorded in the timeline. The workflow stays open and retries on a later wake.
- Run-specific instructions are persisted with an `instruction_added` timeline entry and loaded into the next agent prompt; adding one does not itself trigger inference.
- Pause, resume, interrupt, and terminate endpoints are implemented. Paused workflows continue recording events but defer new agent calls; an in-flight agent activity is allowed to finish. Urgent events and interrupts are processed after resume. Terminate hard-stops Temporal without final output. Instruction text is limited to 4,000 characters per request.
- Docker Compose API service on port 8000 and Next.js operator console on port 3000, alongside PostgreSQL and Temporal.

## Incomplete

- Database migrations, beyond `create_all` during API startup.
- A Docker-backed end-to-end run; Compose syntax was checked, but the services were not started.
- A live Groq request; tests use fake provider responses and no API key is available in this workspace.

## Files changed or added in this milestone

- `backend/app/db/`: SQLAlchemy models, engine/session dependency, schema initialization.
- `backend/app/api/`: supervisor/run routes, run controls, and request/response schemas.
- `backend/app/main.py`: FastAPI application and startup schema initialization.
- `backend/app/temporal/`: durable per-run workflow, event persistence activities, worker registration and sync activity executor; existing no-op workflow remains.
- `backend/app/temporal/policy.py`: small deterministic event-to-wake policy, reused by workflow code and unit tests.
- `backend/app/agent/llm.py`: Groq request, prompt construction, and strict JSON decision validation.
- `backend/app/agent/tools.py`: tool argument contracts, allow-list descriptions, and local mock implementations.
- `backend/app/temporal/activities.py`: agent activity loads order/run context, calls the provider, executes allowed mock tools, and persists memory/timeline/final output.
- `backend/app/temporal/workflow.py`: connects start, events, timer wakes, delivery, close-workflow finalization, and pause/resume/interrupt state to agent execution.
- `web/src/app/operator-console.tsx`, `web/src/lib/`: operator workflows, typed API access, and frontend data contracts.
- `web/next.config.ts`, `web/Dockerfile`, `web/.dockerignore`: same-origin API rewrite and Compose-ready frontend image.
- `backend/app/config.py`, `backend/app/api/runs.py`, `.env.example`: configurable default wake interval and supervisor override wiring.
- `backend/tests/test_api.py`: SQLite-backed API checks with Temporal calls mocked.
- `backend/tests/test_order_workflow.py`, `backend/tests/test_wake_policy.py`: Temporal signal/timer behavior, delivery completion, and wake-policy decisions.
- `backend/tests/test_agent.py`: Groq request contract, prompt context, key/invalid-response handling, and tool validation.
- `backend/requirements.txt`: FastAPI, SQLAlchemy, PostgreSQL driver, Uvicorn, and HTTP test client.
- `docker-compose.yml`, `README.md`, `ARCHITECTURE.md`: API service, run instructions, and implemented-state notes.

## Verification

- Complete Python 3.10 backend suite: **27 passed**, 1 Starlette deprecation warning.
- Temporal integration tests use a fake LLM and local SQLite; they validate wake/sleep behavior, event handling during pause, deferred interrupts, prompt instructions, memory, mock tool action, and final output.
- Next.js frontend `npm run lint`: passed; `npm run build`: passed.
- Browser smoke test rendered the operator console. API calls reported unavailable because backend/Docker services were not running.
- `npm audit --omit=dev --audit-level=high`: passed with zero production dependency advisories.
- `npm install` reported five high advisories in the full dependency tree; the production-only audit found none. The development dependency advisories have not been investigated.
- `docker compose config --quiet`: passed.
- `git -c core.whitespace=cr-at-eol diff --check`: passed using the repository's existing CRLF line endings.
- Docker Desktop's Linux engine is currently unavailable (`docker compose ps` cannot connect to its named pipe), so no containers were started and PostgreSQL/Temporal integration in Compose remains unverified.
- Groq HTTP request/response handling is tested with fake responses; live model availability, credentials, quotas, and output quality remain unverified.

## Why this slice was built

The assignment requires real agent reasoning and tool execution on wake triggers without a continuous inference loop. One worker activity owns prompt assembly, provider calls, validation, mocked tool execution, and persistence. The Temporal workflow remains deterministic, with no separate service or LLM classifier. All mock tools explicitly report simulated effects.

## Next step

Start Docker Desktop and verify the full Compose walkthrough against PostgreSQL and Temporal. Then, with a user-supplied Groq key, verify live provider compatibility and complete the assignment walkthrough/video. Backend tests remain credential-free and hermetic.
