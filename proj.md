# Order Supervisor — requirements (proj.md)

Source of truth: [sagedoc.txt](sagedoc.txt). Items marked **Assumption** are implementation choices, not assignment text.

Chosen decisions:

- Infra: local Docker Compose for Temporal, PostgreSQL, FastAPI, and Next.js.
- LLM: Groq free-tier API for agent inference.
- Agent tools: exactly three are enabled by the operator's explicit scope choice: customer message, internal note, and mark for human review. This intentionally overrides FR-09's assignment minimum of four; do not add or remove tools without approval.
- Quality evaluation: optional isolated RAGAS evaluation over synthetic scenarios; this is an evaluator, not a retrieval system.

This file is the classified requirements analysis. Product code is not part of this document.

---

## 1. Functional requirements

### Must-have for the assignment

- **FR-01** Start one long-running Temporal workflow per order when a run is created. Keep it alive until a terminal state.
- **FR-02** Initialize the workflow with order context and a base instruction from a supervisor config.
- **FR-03** Deliver order-related events into the workflow as Temporal signals.
- **FR-04** Run the agent on three triggers only: workflow start, incoming important signal, scheduled wake-up. Do not run a tight continuous loop.
- **FR-05** Agent can reason, decide whether to act, call tools, update memory/timeline, set wake-up instructions, sleep, and wake later.
- **FR-06** Sleep until a scheduled time; wake on incoming signals; decide if an event is important enough to wake the main agent (lightweight classifier or policy is acceptable).
- **FR-07** Persist per run: timeline of important events/actions, compact memory summary, current workflow status, sleep state or next wake-up time.
- **FR-08** Simple context compaction (summarize older history, keep important events, rolling summary). Sophisticated memory is not required.
- **FR-09** Assignment baseline: at least 4 agent tools. Assignment examples: send customer message, create internal note, escalate issue, mark order for review, schedule next wake-up, close workflow. Tools may be mocked. **Approved implementation deviation:** current operator decision limits the catalog to three (customer message, internal note, mark for human review); retain this gap in submission notes unless the operator approves changing it.
- **FR-10** Event generator/simulator that can send events into a run. Possible types: `order_created`, `payment_confirmed`, `payment_failed`, `shipment_created`, `shipment_delayed`, `delivered`, `refund_requested`, `customer_message_received`, `no_update_for_n_hours`.
- **FR-11** UI: configure supervisor template; start a run; view active and completed runs; inspect timeline and action history; inspect memory summary; inject events; add extra instructions to a live run; interrupt, pause, resume, or terminate a run. UI must be functional, not polished.
- **FR-12** Supervisor config fields: name, base instruction, available tools; optional default wake-up behavior, optional model/config, optional wake aggressiveness. Hardcoded templates are acceptable.
- **FR-13** Add run-specific instructions after start; they become part of run context.
- **FR-14** On finish, produce final summary, important actions taken, key learnings, feedback/recommendations (main agent final step is acceptable).

### Important but secondary

- **FR-15** Event generator can be UI panel, backend endpoint, script, or all of the above. **Assumption:** UI + API is enough to satisfy “inject events”; a script is extra.
- **FR-16** Optional supervisor fields (model choice, default wake-up, aggressiveness) if time allows beyond hardcoded defaults.
- **FR-17** Support the full listed event type set in the simulator so the walkthrough can show several lifecycle paths.

### Optional improvements (assignment “Good-to-Have”)

- **FR-18** Agent-generated wake-up guidance for the classifier.
- **FR-19** Unknown-event escalation.
- **FR-20** `continue_as_new` for very long histories.
- **FR-21** Stronger memory compaction.
- **FR-22** Multiple supervisor templates.
- **FR-23** Richer run analytics.

### Out of scope

Real commerce/messaging integrations, authentication, multi-tenant hardening, advanced retrieval, multiple cooperating agents, polished design.

---

## 2. Non-functional requirements

The assignment does not give numeric SLAs.

- **NFR-01 Performance (must-have):** Agent must not run continuously; inference only on the three triggers.
- **NFR-02 Time-to-complete (must-have):** Intended 1–2 days; smaller reliable demo beats unfinished large system.
- **NFR-03 Maintainability (must-have):** Clean architecture; README setup; short architecture note.
- **NFR-04 Reliability (must-have):** Workflow stays alive across sleeps; events arrive as signals; demo of sleep/wake must work.
- **NFR-05 Stack (must-have):** Next.js App Router, Tailwind, FastAPI, Temporal Python SDK (`temporalio`), PostgreSQL (Supabase allowed but not required).
- **NFR-06 Security:** Authentication is not needed. **Assumption:** no login; public-internet hardening is not required.
- **NFR-07 Scalability:** One-workflow-per-order is the only scale model given. Horizontal scale is not a requirement.

---

## 3. User roles and permissions

The assignment does not define roles. Auth is out of scope.

**Assumption:** a single unauthenticated operator who can do every UI action.

---

## 4. Main user workflows

1. Configure supervisor (name, base instruction, tools, optional wake/model/aggressiveness).
2. Start order run; backend starts one Temporal workflow; agent runs on start.
3. Live supervision: events injected; classifier may wake the agent or leave it sleeping until the timer; agent may call tools, update memory, schedule next wake.
4. Add extra instructions to a live run; they join run context.
5. Interrupt, pause, resume, or terminate.
6. Terminal state: agent writes final summary, actions, learnings, feedback.
7. Inspect active/completed runs: timeline, actions, memory, status, sleep/next wake.

---

## 5. Data entities, relationships, constraints

- **Supervisor:** name, base instruction, available tools; optional default wake-up, model/config, wake aggressiveness.
- **Run:** one Temporal workflow per order; status; sleep state or next wake-up; order context; extra instructions; link to supervisor.
- **TimelineEntry:** important events and actions for a run.
- **Memory:** compact/rolling summary for a run.
- **Event:** typed payload delivered as a workflow signal.
- **ToolCall / Action:** mocked tool results in action history.
- **FinalOutput:** summary, important actions, learnings, feedback.

Constraints: one workflow run per order; workflow lives until terminal state; extra instructions apply after start; tools may be simulated.

**Assumption:** `run_id` maps 1:1 to Temporal workflow id.

---

## 6. API endpoints

Assignment suggests (exact design is up to you):

- `POST /api/supervisors`
- `GET /api/supervisors/{id}`
- `POST /api/runs`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/events`
- `POST /api/runs/{run_id}/instructions`
- `POST /api/runs/{run_id}/interrupt`
- `POST /api/runs/{run_id}/resume`
- `POST /api/runs/{run_id}/terminate`

**Assumption:** `POST /api/runs/{run_id}/pause` because the UI requires pause.

**Assumption:** `GET /api/runs/{run_id}` returns status, sleep/next wake, memory, timeline, actions, and final output when present.

JSON field names are not specified by the assignment. Proposed bodies live in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 7. External services, integrations, configuration

Specified: Temporal Python SDK, PostgreSQL, LLM of choice, mocked tools.

**Assumptions:** local Temporal + Postgres via Docker Compose; Groq API (`GROQ_API_KEY`); Next.js → FastAPI → Temporal and Postgres.

---

## 8. Edge cases, failure scenarios, validation rules

Stated: unimportant events should not always wake the main agent; agent sleeps when no action is needed; simple compaction; unknown events optional; real vendor failures out of scope.

**Assumption for implementation:** reject unknown run ids; persist tool/LLM failures on the timeline rather than crashing the workflow; Temporal keeps the workflow alive across worker restarts.

---

## 9. Acceptance criteria

- **AC-01** One Temporal workflow started per order.
- **AC-02** Order events sent into the workflow as signals.
- **AC-03** Agent wakes on start, signal, and scheduled wake-up.
- **AC-04** Agent can sleep and wake later.
- **AC-05** Agent can call tools.
- **AC-06** Run stores timeline and compact memory.
- **AC-07** UI shows run history and current state.
- **AC-08** UI can inject events and additional instructions.
- **AC-09** Workflow produces a final summary with learnings and feedback.

Deliverables: source, README with setup, short architecture note, walkthrough video.

---

## 10. Ambiguities

Pause vs interrupt vs terminate vs resume semantics; terminal state machine; JSON/DB schemas; classifier implementation; demo timer scale; order fields; Groq model id; whether concurrent runs are required.

**Assumptions unless overridden:**

- Pause: stop agent inference and ignore wake-ups until resume; still record events.
- Interrupt: signal the workflow to run the main agent now.
- Terminate: Temporal-terminate; mark run terminated; skip final agent output unless already written.
- `delivered` triggers final output. The close-workflow tool was removed with the operator-approved three-tool limit. Manual termination is a hard stop and skips final output.
- Short configurable timers for the walkthrough.
- Classifier: simple policy first (delay/fail/refund/customer_message wake immediately; others may wait).

---

## Traceability

| Requirement | Component | Test |
| --- | --- | --- |
| FR-01 / AC-01 | FastAPI run create + `OrderSupervisorWorkflow` | Creating a run starts one workflow with that id |
| FR-02 / FR-12 | Supervisor store + workflow init args | Run starts with template instruction and tools |
| FR-03 / AC-02 / FR-10 | `POST .../events` + workflow signal | Signal received; timeline records event |
| FR-04 / FR-05 / AC-03 / AC-04 | Workflow wait (timer OR signal) + agent activity | Start, signal, and timer each invoke agent once per trigger |
| FR-06 | Classifier policy before main agent | Unimportant event does not call main agent |
| FR-07 / FR-08 / AC-06 | Postgres timeline/memory + compaction | Timeline grows; memory stays compact |
| FR-09 / AC-05 | Mocked tool activities | Tool call persisted as action |
| FR-11 / AC-07 / AC-08 | Next.js pages | List/detail, inject event, add instruction, controls |
| FR-13 | `POST .../instructions` + signal | Later agent prompt includes extra instruction |
| FR-14 / AC-09 | Workflow finalization | Terminal run has summary, actions, learnings, feedback |
| NFR-01 | Workflow sleep design | Worker idle between triggers |
| NFR-05 | Next.js + FastAPI + temporalio + Postgres | README/setup verification |
| Deliverables | README, architecture note, video | Checklist |
| FR-18–23 | Optional modules | Tests only if implemented |
