---
name: order-supervisor
description: >-
  Guides implementation of the Sage Order Supervisor POC (Temporal per-order
  workflow, FastAPI, Next.js, PostgreSQL, Groq). Use when building, changing,
  or reviewing this assignment; when the user mentions supervisors, runs,
  signals, wake/sleep, timeline, memory, tools, or sagedoc.txt; or when adding
  stack, Docker, or LLM code.
---

# Order Supervisor

## Source of truth

Treat [sagedoc.txt](../../../sagedoc.txt) (repo root) as the only assignment requirements. Use [proj.md](../../../proj.md) for the classified requirements analysis and [ARCHITECTURE.md](../../../ARCHITECTURE.md) for the approved POC design. Use [PROMPTS.md](../../../PROMPTS.md) as the append-only user prompt log.

- Do not invent requirements, APIs, fields, SLAs, or roles that are not in that file.
- Implementation choices below are labeled **Assumption**. Do not present them as assignment text.
- Prefer a small, reliable POC over extra features. Intended build: 1–2 days.

## When implementing

1. Re-read `sagedoc.txt` for the relevant section before coding.
2. Ship must-haves first. Good-to-haves only after the walkthrough path works.
3. Do not add out-of-scope work.

## Required stack

- Next.js App Router + Tailwind CSS
- FastAPI
- Temporal Python SDK (`temporalio`)
- PostgreSQL (Supabase allowed, not required)
- LLM/tool orchestration: implementer’s choice

**Assumption (infra):** local Docker Compose for Temporal, PostgreSQL, FastAPI, and Next.js.

**Assumption (LLM):** Groq free-tier API for agent inference (and optionally the classifier). `GROQ_API_KEY` via env; never commit keys. Pick a current Groq free model at implement time.

## Architecture (target)

```
Next.js UI → FastAPI → PostgreSQL
                  ↘ Temporal workflow per order
                       → wake classifier (policy or lightweight LLM)
                       → main agent → mocked tools, memory, timeline
Event injector → FastAPI → workflow signal
```

- One long-running Temporal workflow per order until a terminal state.
- **Assumption:** `run_id` maps 1:1 to Temporal workflow id.
- Agent inference only on three triggers: workflow start, important incoming signal, scheduled wake-up. No tight continuous loop.
- Events enter the workflow as Temporal signals.

## Must-have

- Workflow init with order context + supervisor base instruction.
- Sleep until scheduled time; wake on signals; classifier/policy decides if an event is important enough to run the main agent. Simple is acceptable.
- Persist per run: timeline, compact/rolling memory summary, status, sleep state or next wake-up. Simple compaction only.
- Assignment baseline: at least 4 mocked tools. This repository has an operator-approved exception limiting the enabled catalog to three: customer message, internal note, and mark for human review. Do not change that scope without explicit approval; report the FR-09 deviation in assignment handoff.
- Event simulator covering listed types: `order_created`, `payment_confirmed`, `payment_failed`, `shipment_created`, `shipment_delayed`, `delivered`, `refund_requested`, `customer_message_received`, `no_update_for_n_hours`.
- **Assumption:** UI + API is enough for inject events; a separate script is extra.
- Functional UI: supervisor template; start run; list active/completed; inspect timeline, actions, memory; inject events; extra live-run instructions; interrupt, pause, resume, terminate.
- Supervisor config: name, base instruction, available tools; optional default wake-up, model/config, wake aggressiveness. Hardcoded templates are acceptable.
- Extra instructions after start become part of run context.
- On finish: final summary, important actions, key learnings, feedback/recommendations (main agent final step is fine).
- README setup + short architecture note. Walkthrough video is a later deliverable, not this skill’s job unless asked.

Suggested APIs from the assignment (exact design is up to you):

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

UI also requires **pause**. Suggested list has no pause.

**Assumption:** `POST /api/runs/{run_id}/pause`.

**Assumption:** `GET /api/runs/{run_id}` returns status, sleep/next wake, memory, timeline, actions, and final output when present.

JSON body field names are not specified. Do not treat invented schemas as requirements.

## Good-to-have (not mandatory)

- Agent-generated wake-up guidance for the classifier
- Unknown-event escalation
- `continue_as_new` for very long histories
- Stronger memory compaction
- Multiple supervisor templates
- Richer run analytics

## Out of scope

Do not build: real commerce/messaging integrations, authentication, multi-tenant hardening, advanced retrieval, multiple cooperating agents, polished design.

**Assumption:** single unauthenticated operator; no customer/admin roles unless the user later requests them.

## Control-flow assumptions (needed to implement; not assignment text)

Use these unless the user overrides:

- **Pause:** stop agent inference and ignore wake-ups until resume; still record events.
- **Interrupt:** signal the workflow to run the main agent now.
- **Terminate:** Temporal-terminate the workflow; mark run terminated; skip final agent output unless already written.
- **Terminal:** `delivered` triggers final output. The close-workflow tool is excluded by the approved three-tool limit. Manual termination is a hard stop and skips final output.
- Short configurable timers (seconds/minutes) so the walkthrough can show sleep/wake.
- Classifier: simple policy first (delay/fail/refund/customer_message wake immediately; others may wait). Optional Groq call if time.
- Reject unknown run ids. Persist tool/LLM failures on the timeline rather than crashing the workflow. Rely on Temporal to keep the workflow alive across worker restarts.

## Acceptance (must pass)

- One Temporal workflow per order
- Events delivered as signals
- Agent wakes on start, important signal, and scheduled wake-up; can sleep and wake later
- Agent can call tools
- Timeline + compact memory stored
- UI shows history/state; can inject events and extra instructions
- Final summary with learnings and feedback

Walkthrough path: create supervisor → start run → send events → sleep/wake → tools → extra instructions on a live run → interrupt or terminate → final output.

## Gaps — do not invent as requirements

Pause vs interrupt vs terminate semantics, terminal state machine, JSON/DB schemas, classifier implementation, demo timer scale, order fields, Groq model id, concurrent-run requirements. Flag gaps; use the assumptions above only when coding.
