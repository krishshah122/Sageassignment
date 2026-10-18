# Live project status

Last updated: 2026-10-18

## Product and current scope

This repository is the Order Supervisor POC described in [sagedoc.txt](./sagedoc.txt). Its approved target stack and requirements are recorded in [proj.md](./proj.md) and [ARCHITECTURE.md](./ARCHITECTURE.md).

The backend persistence/API foundation, deterministic wake/sleep orchestration, Groq-backed agent/tool execution, backend run controls, and Next.js operator console are implemented. A full synthetic order lifecycle has now been exercised live through PostgreSQL, Temporal, the worker, and Groq. This remains a proof of concept, not a production order-management system.

## Implemented

- Environment-backed backend settings and the existing no-op Temporal workflow.
- SQLAlchemy models for supervisors, runs, timeline entries, run memory, and final output.
- FastAPI supervisor create/list/detail endpoints.
- FastAPI run create/list/detail endpoints. Run creation persists a row and starts an `OrderSupervisorWorkflow` whose workflow ID is the run UUID.
- Event injection for all nine assignment event types. Events are sent as Temporal signals and persisted by worker activities. `delivered` requests agent finalization; the workflow completes after final output is stored.
- A deterministic wake policy that immediately requests a wake for payment failures, shipment delays, refund requests, and customer messages. Other event types are persisted without changing the scheduled wake.
- Durable Temporal timer wake requests. Runs record the initial start trigger, important-event triggers, next wake time, and scheduled triggers in run state/timeline. Supervisor wake interval overrides `DEFAULT_WAKEUP_SECONDS` (30-second default).
- Groq chat-completions adapter requests JSON Schema output and validates it locally. The model is configurable and defaults to `openai/gpt-oss-20b`. The API key is injected only into the worker container.
- Agent execution on start, urgent event, scheduled timer, and finalization triggers. Prompt context includes base/run instructions, order context, recent timeline, memory, and triggering events.
- Six schema-validated mocked tools: send customer message, create internal note, escalate issue, mark for review, schedule next wake, and close workflow. These tools make no real external calls.
- Agent summaries, tool action results/failures, updated compact memory, LLM errors, and final summary/actions/learnings/feedback are stored in the existing tables.
- Provider, missing-key, and malformed-response errors use bounded Temporal activity retries and are recorded in the timeline. The workflow stays open and retries on a later wake.
- Run-specific instructions are persisted with an `instruction_added` timeline entry and loaded into the next agent prompt; adding one does not itself trigger inference.
- Pause, resume, interrupt, and terminate endpoints are implemented. Paused workflows continue recording events but defer new agent calls; an in-flight agent activity is allowed to finish. Urgent events and interrupts are processed after resume. Terminate hard-stops Temporal without final output. Instruction text is limited to 4,000 characters per request.
- Docker Compose API service on port 8000 and Next.js operator console on port 3000, alongside PostgreSQL and Temporal.

## Incomplete

- Database migrations; the API still initializes tables with `create_all`.
- Real commerce/customer integrations; the three allowed agent tools are local simulations.
- Broader live-provider quality and quota testing; Groq schema output is best-effort and remains locally validated, so individual inferences can still fail.
- The previously observed five high-severity development dependency audit findings have not been investigated; the production-only audit reported none.

## Files changed or added in this milestone

- `backend/app/db/`: SQLAlchemy models, engine/session dependency, schema initialization.
- `backend/app/api/`: supervisor/run routes, run controls, and request/response schemas.
- `backend/app/main.py`: FastAPI application and startup schema initialization.
- `backend/app/temporal/`: durable per-run workflow, event persistence activities, worker registration and sync activity executor; existing no-op workflow remains.
- `backend/app/temporal/policy.py`: small deterministic event-to-wake policy, reused by workflow code and unit tests.
- `backend/app/agent/llm.py`: Groq request, prompt construction, and strict JSON decision validation, including exact final-output value types.
- `backend/app/agent/tools.py`: tool argument contracts, allow-list descriptions, and local mock implementations.
- `backend/app/temporal/activities.py`: agent activity loads order/run context, calls the provider, executes allowed mock tools, and persists memory/timeline/final output.
- `backend/app/temporal/workflow.py`: connects start, events, timer wakes, delivery, close-workflow finalization, and pause/resume/interrupt state to agent execution.
- `web/src/app/operator-console.tsx`, `web/src/lib/`: operator workflows, typed API access, and frontend data contracts.
- `web/next.config.ts`, `web/Dockerfile`, `web/.dockerignore`: same-origin API rewrite and Compose-ready frontend image.
- `backend/app/config.py`, `backend/app/api/runs.py`: configurable default wake interval and supervisor override wiring.
- `backend/tests/test_api.py`: SQLite-backed API checks with Temporal calls mocked.
- `backend/tests/test_order_workflow.py`, `backend/tests/test_wake_policy.py`: Temporal signal/timer behavior, delivery completion, and wake-policy decisions.
- `backend/tests/test_agent.py`: Groq request contract, prompt context, key/invalid-response handling, tool validation, and final-output prompt requirements.
- `backend/requirements.txt`: FastAPI, SQLAlchemy, PostgreSQL driver, Uvicorn, and HTTP test client.
- `docker-compose.yml`: API service configuration with worker/API URLs aligned on SQLAlchemy's `postgresql` dialect and installed `psycopg2-binary` driver.
- `README.md`, `ARCHITECTURE.md`, `help.md`: run/setup documentation, architecture notes, synthetic walkthrough, expected outcomes, endpoint reference, and troubleshooting.
- `worker-and-order.md`: plain-language, code-grounded explanation of the order run, Temporal workflow, worker activities, Groq agent, simulated tools, and where to inspect each part. Linked from `README.md` and `help.md`.
- `backend/tests/test_order_workflow.py`: the workflow test now enables `create_internal_note` and checks for a successful simulated tool result, rather than merely checking for an action timeline entry.
- Agent tool catalog is restricted consistently in backend schemas, action validation, and the UI to `send_customer_message`, `create_internal_note`, and `mark_order_for_review`. API validation rejects unsupported, duplicate, and more-than-three tool selections. Wake intervals remain a structured agent decision field; delivery events, not a tool, initiate finalization.
- Added an optional, isolated RAGAS evaluation image and three synthetic golden scenarios. It runs real Groq agent decisions and scores factual correctness, faithfulness to supplied evidence, response relevance, and instruction adherence; evaluation dependencies are not installed in the normal API/worker images.

## Verification

- Backend suite after enabling Groq JSON Schema response mode (Python 3.12): **27 passed**, 1 Starlette deprecation warning.
- Latest live acceptance workflow `ae1cfa61-ec90-48d9-9959-c0a6d0e5d185`: completed start inference, persisted memory, accepted/persisted `delivered`, completed final inference, saved final output, and had zero `agent_error` entries.
- Temporal integration tests use a fake LLM and local SQLite; they validate wake/sleep behavior, event handling during pause, deferred interrupts, prompt instructions, memory, mock tool action, and final output.
- Focused backend checks after tightening mock-tool workflow coverage: `test_order_workflow.py` and `test_agent.py` **6 passed**. The workflow test now verifies a `create_internal_note` action succeeds and records `created: simulated`.
- `git -c core.whitespace=cr-at-eol diff --check`: passed after the documentation and test changes.
- Backend tests for the three-tool limit and RAGAS dataset preparation: pending.
- Optional real-Groq RAGAS scores: pending.
- Live synthetic workflow `14dcdcdd-512c-45bc-a9e6-3e20da6493e3`: initial Groq inference persisted an `agent_run` and memory; a `delivered` event triggered finalization; status reached `completed`, with two agent runs, final output, and no `agent_error` entries.
- Two earlier synthetic attempts during live schema-contract debugging were terminated and remain in the local database: `916ead1e-443f-4805-b722-81fb67561b5a` and `711ce6ff-ff85-48e2-a57c-e8f876fbb127`. There is no run-delete endpoint.
- The earlier `ORD-DEMO-GROQ-TEST` run from the preceding verification attempt (`ec1ed555-7cbd-4545-95ac-2abebf21645b`) is also terminated and remains in the database.
- A later live retest (`5d050849-de4c-4983-bb31-4b519403fae5`) returned an empty `memory_summary`; local Pydantic validation rejected it and the run was terminated as cleanup. The agent request now sends the Pydantic JSON Schema in Groq JSON Schema mode and explicitly requires a non-empty memory summary; the subsequent successful acceptance workflow above verifies the fix for that input. JSON Schema mode is best-effort (`strict: false`), so local validation and the visible error path remain necessary.
- Docker Compose currently has all six services running. API docs and the dashboard returned HTTP 200; the UI's proxied supervisor, run-list, and run-detail requests returned HTTP 200 after reload. The completed verification run is visible in the console.
- Worker configuration was checked without revealing the key: Groq key present, model `openai/gpt-oss-20b`, SQLAlchemy driver `postgresql`, and `psycopg2` import available.
- Next.js `npm run lint` and `npm run build` passed in the earlier frontend milestone; they were not rerun because this task changed no frontend code.
- `npm audit --omit=dev --audit-level=high`: passed with zero production dependency advisories.
- `npm install` reported five high advisories in the full dependency tree; the production-only audit found none. The development dependency advisories have not been investigated.
- `docker compose config --quiet`: passed.
- `git -c core.whitespace=cr-at-eol diff --check`: passed using the repository's existing CRLF line endings.
- Initial parallel Compose Bake image export failed with an `image ... already exists` collision for the API image. Re-running with PowerShell `$env:COMPOSE_BAKE = "false"` succeeded. README now documents this Windows workaround.
- Live testing exposed inconsistent Groq output shapes (including empty memory, malformed final fields, and final output on a non-final response). The agent now requests the Pydantic JSON Schema and the prompt explicitly requires non-empty memory, `final_output: null` before finalization, and object-valued `important_actions`; the latest full run verifies the contract for the tested input.
- `.env.example` is absent in the current worktree. Setup instructions now tell the operator to create/edit the git-ignored root `.env` directly; the existing local `.env` was not read or changed.

## Why this slice was built

The assignment requires real agent reasoning and tool execution on wake triggers without a continuous inference loop. One worker activity owns prompt assembly, provider calls, validation, mocked tool execution, and persistence. The Temporal workflow remains deterministic, with no separate service or LLM classifier. All mock tools explicitly report simulated effects.

## Next step

Open <http://localhost:3000> and inspect the latest completed synthetic run `ae1cfa61-ec90-48d9-9959-c0a6d0e5d185`. Follow [help.md](./help.md) for the setup/manual walkthrough or [worker-and-order.md](./worker-and-order.md) for the detailed worker and workflow explanation. The app is already running in Docker; no additional POC features are required for the core assignment path. If the scope later changes toward production use, assess migrations, dependency advisories, authentication, and real integrations separately.
