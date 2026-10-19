# Order, Workflow, Temporal, and Worker: How This POC Works

This note explains the running application in plain language, then follows the real code path in more detail. It describes the current implementation; it is not a proposal for future features.

## Short version

Think of one pretend order as one case in a support desk:

- **Order:** the sample purchase and its details, such as an order ID, current status, items, and shipping information. The operator supplies this data; this POC is not connected to a shop or a carrier.
- **Supervisor:** the saved instruction card: what the AI should pay attention to, which simulated tools it may use, and how long to wait between checks.
- **Run:** one monitoring session for one order. Creating the supervisor alone does not start a run.
- **Workflow:** the durable watcher for that run. Temporal remembers that it is waiting, even while no code is actively checking the order.
- **Worker:** the background application process that polls Temporal for work. When a workflow asks for an activity, the worker runs the Python activity, calls Groq when appropriate, and saves results.
- **Agent:** the AI decision made by the worker on a start, important-event, interrupt, or scheduled wake. It reads the supplied order context and event history, then returns a structured decision.
- **Tool:** one of three small operations the agent may request. They are mocks/simulations; they only produce a result for the demo and do not contact a customer, shop, carrier, or other service.

The typical path is:

```text
Operator in browser
    → FastAPI saves supervisor/run and talks to Temporal
    → Temporal starts one OrderSupervisorWorkflow for the run
    → Worker polls Temporal and performs workflow activities
    → Worker calls Groq for an agent decision on a wake
    → Worker validates the decision, runs any allowed mock tools, and saves results in PostgreSQL
    → Workflow waits for another signal or its timer, or completes after finalization
    → Browser reads status, memory, timeline, and final output from FastAPI
```

## What “worker” means here

The worker is not a separate website or a person. It is the `worker` Docker Compose service running:

```text
python -m app.temporal.worker
```

It connects to the Temporal server at `temporal:7233`, registers the `OrderSupervisorWorkflow` and activity functions, and polls the `order-supervisor` task queue. It has a pool of four threads for synchronous database activities.

The worker does not continuously scan orders and does not decide by itself to start a new order. It waits for Temporal to give it workflow or activity tasks. The workflow defines when work is needed; the worker executes that work.

The worker runs these activities:

| Activity | What it does |
| --- | --- |
| `mark_run_running` | Marks a newly started run as running in PostgreSQL. |
| `record_order_event` | Saves an event received by the workflow to the order's timeline. |
| `run_agent` | Loads supervisor/run context and recent history, requests a Groq decision, validates it, executes allowed mock tools, saves memory and timeline records, and writes final output when finalizing. |
| `record_wake` | Stores the wake reason, event types, next wake time, and sleeping status. |
| `record_agent_error` | Saves an agent failure in the timeline after the configured activity attempts fail. |
| `ping` | Supports the small NoopWorkflow used to verify Temporal wiring; it is not part of normal order monitoring. |

To watch worker logs from PowerShell in the repository folder:

```powershell
docker compose logs -f worker
```

The worker logs show connection, polling, provider HTTP status, and errors. They are technical logs, not the full human-readable order history. The order's summary, actions, memory, and events are shown in the operator UI at <http://localhost:3000>.

## What “workflow” means here

A Temporal workflow is the durable program that controls the long-running sequence. The class is `OrderSupervisorWorkflow` in `backend/app/temporal/workflow.py`. The API starts it with the run UUID as its workflow ID and passes in the order ID/context, supervisor instruction, enabled tools, and default wake interval.

The workflow does not call PostgreSQL or Groq directly. To do external or slow work, it asks Temporal to schedule an activity; a worker executes that activity. Workflow code uses Temporal's deterministic clock, conditions, signals, and durable timers so it can replay safely.

For each run, the workflow:

1. Marks the run as running.
2. Requests an agent activity for the `start` trigger.
3. Records the next wake time and waits; it does not poll the carrier or repeatedly call the AI while asleep.
4. Accepts event, pause, resume, and interrupt signals from the API.
5. Records each accepted order event through a worker activity.
6. Uses the deterministic policy in `backend/app/temporal/policy.py` to decide whether an event should wake the agent immediately.
7. Wakes for a scheduled timer or interrupt as well as the immediate event policy.
8. When a `delivered` event is received, runs a final agent step, saves final output, marks the run completed, and returns.

Immediate-wake event types are `payment_failed`, `shipment_delayed`, `refund_requested`, and `customer_message_received`. Other accepted event types are recorded and normally wait for the current timer. This policy is simple code, not another AI agent, so it does not make an extra Groq request.

The workflow is useful because a long wait is represented as durable Temporal state and a timer, rather than a Python loop that constantly checks the order. Temporal can show the workflow ID, status, signal history, timers, and activity history in its UI.

## What the AI agent does

The agent is a Groq chat-completions request made by the `run_agent` activity in `backend/app/temporal/activities.py`, using the prompt/client functions in `backend/app/agent/llm.py`.

For each invocation, it receives:

- supervisor base instructions;
- run-specific instructions saved by the operator;
- order ID and order context;
- the previous compact memory summary;
- up to the most recent 30 timeline entries;
- newly received event(s), if any;
- the reason it woke and whether this is the final step; and
- descriptions/schemas only for tools enabled on that supervisor.

It returns a structured decision containing a short summary, updated memory, zero or more requested actions, an optional next wake interval, and (only during finalization) final output fields. The worker validates the returned JSON locally before saving or acting on it.

The model is **not** watching a real website or order feed. In this POC, an operator types order details and injects events through the UI. Those values are included in the Groq request. Use synthetic data and do not include information you are not allowed to send to Groq.

## Do mock tools actually run?

**Yes, but only if all three things happen:**

1. The supervisor enables that tool.
2. The agent returns an action requesting it.
3. The returned arguments pass validation.

If all three conditions pass, `run_agent` calls `execute_mock_tool` in `backend/app/agent/tools.py` and records the result as a timeline entry with `kind=action` and `status=succeeded`. Invalid arguments or a disabled tool are recorded as a failed action. If the agent returns no actions, no tool runs.

| Tool name | What the mock does | What it does not do |
| --- | --- | --- |
| `send_customer_message` | Records the proposed message with `delivery: simulated`. | Does not send an email, text, or chat message. |
| `create_internal_note` | Records the note with `created: simulated`. | Does not write to a shop's order system. |
| `mark_order_for_review` | Records a simulated review flag and reason. | Does not change a real order or notify an operator. |

Important: the POC restricts supervisors to these three tools. Enabling a tool only grants permission. The model still chooses whether it is useful, so a run will not necessarily execute an enabled tool. The finalization step is intentionally not allowed to request tools. Wake timing is returned in the structured agent decision and implemented by the Temporal workflow; it is not a fourth tool. Delivery finalizes through the `delivered` event.

## How to see the different parts

| Place | What it shows |
| --- | --- |
| <http://localhost:3000> | Main operator view: supervisors, order runs, status, run memory, timeline, actions, and final report. |
| <http://localhost:8000/docs> | FastAPI endpoint reference; it is not a workflow dashboard. |
| <http://localhost:8080> | Temporal UI. Open the `default` namespace and inspect the workflow whose ID is the run UUID. Its history shows signals and activities; it does not show the UI's formatted final report. |
| PowerShell `docker compose logs -f worker` | Worker connection, polling, Groq HTTP status, and runtime errors. |
| PostgreSQL | Saved supervisors, runs, timeline, memory, and final output. The browser uses the API rather than accessing the database directly. |

## End-to-end example

### A. Save a supervisor (configuration only)

Use the UI's supervisor form:

- Name: `Demo order watcher`
- Instruction: `Watch this synthetic order. Summarize only the facts provided. When it is marked delivered, write a final report.`
- Enable `create_internal_note` if you want the agent to be allowed to request a simulated note.
- Wake interval: `3600` seconds for a short demo.

Saving the supervisor creates configuration in PostgreSQL. It does **not** start a workflow or call Groq.

### B. Start a run (this starts the workflow)

Select that supervisor and enter:

Order ID:

```text
DEMO-1001
```

Order context:

```json
{
  "status": "in_transit",
  "items": ["synthetic coffee mug"],
  "shipping": {
    "carrier": "Example Delivery",
    "tracking_status": "in_transit"
  }
}
```

Click **Start order run**. FastAPI creates the run row and starts Temporal workflow `OrderSupervisorWorkflow` with the run ID. The worker performs the start activity; after Groq responds, the UI should show an agent summary, memory, and timeline. The workflow then sleeps until a signal or its timer.

### C. Inject an important event

Send event type `shipment_delayed` with:

```json
{
  "reason": "Synthetic weather delay",
  "source": "demo"
}
```

FastAPI sends the event as a Temporal signal. The worker records it. Because `shipment_delayed` is an immediate-wake type, the workflow asks the worker to run the agent again. If `create_internal_note` is enabled and the AI requests a valid note, the timeline shows a successful simulated action.

### D. Finish with delivery

Send event type `delivered` with:

```json
{
  "source": "demo",
  "note": "The pretend package was delivered."
}
```

The workflow asks the worker for a final Groq decision. The worker saves final summary, important actions, learnings, feedback, and final status `completed`. The UI shows the final report. These events change only the POC's saved data.

## Local verification commands

From PowerShell in the repository root:

```powershell
docker compose ps
docker compose logs -f worker
docker compose exec -T api pytest -q /srv/tests
```

The automated tests use a fake Groq response and Temporal's test environment; they do not consume provider quota. The manual live walkthrough calls Groq on start, each immediate event/interrupt, and finalization, so a short demo with one start, one delayed event, and one delivery event normally requests three inferences.

## Important limits

- This is a local proof of concept, not a live order-monitoring service.
- The worker processes queued Temporal activities; it does not independently look up or poll orders.
- Mock tools only record simulated effects.
- Groq schema mode is best-effort, and the application still validates responses. Invalid responses can be logged as agent errors and retried according to the workflow/activity behavior.
- The `GROQ_API_KEY` belongs in the local ignored `.env` file and is given only to the worker container. Never put it in order context or a screenshot.
- The run UUID is the Temporal workflow ID. The order ID is the business/test identifier displayed to the operator; they are different values.
