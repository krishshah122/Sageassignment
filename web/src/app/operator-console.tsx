"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { apiRequest } from "@/lib/api";
import {
  availableTools,
  eventTypes,
  type Collection,
  type RunDetail,
  type RunSummary,
  type Supervisor,
  type TimelineEntry,
} from "@/lib/types";

const terminalStatuses = new Set([
  "completed",
  "terminated",
  "terminating",
  "failed",
]);

function readable(value: string): string {
  return value.replaceAll("_", " ");
}

function formatDate(value: string | null): string {
  if (!value) return "Not scheduled";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

function isActive(run: RunSummary): boolean {
  return !terminalStatuses.has(run.status);
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`status-badge status-${status}`}>
      <span className="status-dot" />
      {readable(status)}
    </span>
  );
}

function SectionTitle({
  eyebrow,
  title,
  detail,
}: {
  eyebrow: string;
  title: string;
  detail?: string;
}) {
  return (
    <div className="mb-5">
      <p className="eyebrow">{eyebrow}</p>
      <h2 className="mt-1 text-lg font-semibold tracking-tight text-slate-900">
        {title}
      </h2>
      {detail ? <p className="mt-1 text-sm text-slate-500">{detail}</p> : null}
    </div>
  );
}

export default function OperatorConsole() {
  const selectedRunIdRef = useRef("");
  const [supervisors, setSupervisors] = useState<Supervisor[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedRun, setSelectedRun] = useState<RunDetail | null>(null);
  const [selectedSupervisorId, setSelectedSupervisorId] = useState("");
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [supervisorName, setSupervisorName] = useState("Order supervisor");
  const [baseInstruction, setBaseInstruction] = useState(
    "Monitor this order. Act only when needed, use the available tools, and never invent order facts.",
  );
  const [tools, setTools] = useState<string[]>(
    availableTools.map((tool) => tool.id),
  );
  const [wakeSeconds, setWakeSeconds] = useState("30");
  const [model, setModel] = useState("");

  const [orderId, setOrderId] = useState("");
  const [orderContext, setOrderContext] = useState(
    '{\n  "customer": "Sample customer",\n  "items": ["SKU-1"]\n}',
  );
  const [eventType, setEventType] = useState<string>("shipment_delayed");
  const [eventPayload, setEventPayload] = useState('{"reason":"Weather delay"}');
  const [instruction, setInstruction] = useState("");

  const refreshDashboard = useCallback(async () => {
    try {
      const [supervisorResponse, runResponse] = await Promise.all([
        apiRequest<Collection<Supervisor>>("/api/supervisors"),
        apiRequest<Collection<RunSummary>>("/api/runs"),
      ]);
      setSupervisors(supervisorResponse.items);
      setRuns(runResponse.items);
      setSelectedSupervisorId((current) =>
        supervisorResponse.items.some((item) => item.id === current)
          ? current
          : (supervisorResponse.items[0]?.id ?? ""),
      );

      let runId = selectedRunIdRef.current;
      if (!runResponse.items.some((item) => item.id === runId)) {
        runId = runResponse.items[0]?.id ?? "";
        selectedRunIdRef.current = runId;
        setSelectedRunId(runId);
      }
      if (runId) {
        const detail = await apiRequest<RunDetail>(`/api/runs/${runId}`);
        setSelectedRun(detail);
      } else {
        setSelectedRun(null);
      }
      setConnected(true);
      setError("");
    } catch (cause) {
      setConnected(false);
      setError(
        cause instanceof Error
          ? cause.message
          : "The API could not be reached.",
      );
    } finally {
      setInitialLoad(false);
    }
  }, []);

  useEffect(() => {
    const initialRefresh = window.setTimeout(
      () => void refreshDashboard(),
      0,
    );
    const timer = window.setInterval(() => void refreshDashboard(), 5000);
    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(timer);
    };
  }, [refreshDashboard]);

  function chooseRun(runId: string) {
    selectedRunIdRef.current = runId;
    setSelectedRunId(runId);
    setSelectedRun(null);
    setError("");
    void apiRequest<RunDetail>(`/api/runs/${runId}`)
      .then(setSelectedRun)
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : "Could not load run.");
      });
  }

  async function handleCreateSupervisor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const created = await apiRequest<Supervisor>("/api/supervisors", {
        method: "POST",
        body: JSON.stringify({
          name: supervisorName,
          base_instruction: baseInstruction,
          available_tools: tools,
          default_wakeup_seconds: Number(wakeSeconds),
          model: model.trim() || null,
        }),
      });
      setSelectedSupervisorId(created.id);
      setNotice("Supervisor saved. It is ready for a new order run.");
      await refreshDashboard();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not save supervisor.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const context: Record<string, unknown> = JSON.parse(orderContext);
      const created = await apiRequest<RunSummary>("/api/runs", {
        method: "POST",
        body: JSON.stringify({
          supervisor_id: selectedSupervisorId,
          order_id: orderId,
          order_context: context,
        }),
      });
      selectedRunIdRef.current = created.id;
      setSelectedRunId(created.id);
      setSelectedRun(null);
      setOrderId("");
      setNotice(`Run started for ${created.order_id}.`);
      await refreshDashboard();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not start the order run.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedRunId) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const payload: Record<string, unknown> = JSON.parse(eventPayload);
      await apiRequest<{ status: string }>(
        `/api/runs/${selectedRunId}/events`,
        {
          method: "POST",
          body: JSON.stringify({ type: eventType, payload }),
        },
      );
      setNotice(`${readable(eventType)} event sent to the workflow.`);
      await refreshDashboard();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not send the event.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitInstruction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedRunId) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await apiRequest<RunSummary>(
        `/api/runs/${selectedRunId}/instructions`,
        {
          method: "POST",
          body: JSON.stringify({ text: instruction }),
        },
      );
      setInstruction("");
      setNotice("Instruction saved for the next agent run.");
      await refreshDashboard();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not save the instruction.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function runControl(
    control: "pause" | "resume" | "interrupt" | "terminate",
  ) {
    if (!selectedRunId) return;
    if (
      control === "terminate" &&
      !window.confirm(
        "Terminate this workflow permanently? It will not produce final output.",
      )
    ) {
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await apiRequest<RunSummary>(
        `/api/runs/${selectedRunId}/${control}`,
        { method: "POST" },
      );
      setNotice(
        control === "interrupt"
          ? "Interrupt queued. If paused, it will run after resume."
          : `Run ${readable(updated.status)}.`,
      );
      await refreshDashboard();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : `Could not ${control} the run.`,
      );
    } finally {
      setBusy(false);
    }
  }

  function toggleTool(toolId: string) {
    setTools((current) =>
      current.includes(toolId)
        ? current.filter((item) => item !== toolId)
        : [...current, toolId],
    );
  }

  const activeCount = runs.filter(isActive).length;
  const pausedCount = runs.filter((run) => run.status === "paused").length;
  const completedCount = runs.filter(
    (run) => run.status === "completed",
  ).length;

  return (
    <main className="min-h-screen bg-[#f4f6f4] text-slate-800">
      <header className="border-b border-slate-200/80 bg-white">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-emerald-950 text-sm font-bold tracking-wide text-emerald-100">
              OS
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900">
                Order Supervisor
              </p>
              <p className="text-xs text-slate-500">Operations console</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span
              className={`flex items-center gap-2 text-xs font-medium ${
                connected ? "text-emerald-800" : "text-rose-700"
              }`}
            >
              <span
                className={`size-2 rounded-full ${
                  connected ? "bg-emerald-500" : "bg-rose-500"
                }`}
              />
              {connected ? "API connected" : "API unavailable"}
            </span>
            <button
              className="button-secondary !px-3 !py-2"
              onClick={() => void refreshDashboard()}
              type="button"
            >
              Refresh
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1500px] px-5 py-7 sm:px-8 sm:py-9">
        <section className="mb-7 rounded-2xl bg-emerald-950 px-6 py-7 text-white shadow-sm sm:px-8">
          <div className="flex flex-col justify-between gap-7 lg:flex-row lg:items-end">
            <div className="max-w-2xl">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-300">
                Live order operations
              </p>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
                Keep every order moving.
              </h1>
              <p className="mt-3 max-w-xl text-sm leading-6 text-emerald-100/75">
                Start a durable supervisor, follow its decisions, and step in
                whenever an order needs human direction.
              </p>
            </div>
            <div className="grid grid-cols-3 gap-3 sm:min-w-[360px]">
              <Metric label="Active" value={activeCount} />
              <Metric label="Paused" value={pausedCount} />
              <Metric label="Completed" value={completedCount} />
            </div>
          </div>
        </section>

        {error ? (
          <div
            className="mb-5 flex items-start justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
            role="alert"
          >
            <span>{error}</span>
            <button
              aria-label="Dismiss error"
              className="font-semibold"
              onClick={() => setError("")}
              type="button"
            >
              ×
            </button>
          </div>
        ) : null}
        {notice ? (
          <div
            className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900"
            role="status"
          >
            {notice}
          </div>
        ) : null}

        <div className="grid items-start gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <aside className="space-y-5">
            <section className="panel-card">
              <SectionTitle
                eyebrow="Configuration"
                title="Create a supervisor"
                detail="Choose what this agent may do for each order."
              />
              <form className="space-y-4" onSubmit={handleCreateSupervisor}>
                <Field label="Supervisor name">
                  <input
                    className="form-input"
                    onChange={(event) => setSupervisorName(event.target.value)}
                    required
                    value={supervisorName}
                  />
                </Field>
                <Field label="Base instruction">
                  <textarea
                    className="form-input min-h-24 resize-y"
                    onChange={(event) => setBaseInstruction(event.target.value)}
                    required
                    value={baseInstruction}
                  />
                </Field>
                <fieldset>
                  <legend className="mb-2 text-xs font-semibold text-slate-600">
                    Available simulated tools
                  </legend>
                  <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
                    {availableTools.map((tool) => (
                      <label
                        className="flex items-center gap-2 text-xs text-slate-600"
                        key={tool.id}
                      >
                        <input
                          checked={tools.includes(tool.id)}
                          className="size-4 accent-emerald-800"
                          onChange={() => toggleTool(tool.id)}
                          type="checkbox"
                        />
                        {tool.label}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Wake interval (seconds)">
                    <input
                      className="form-input"
                      min="1"
                      onChange={(event) => setWakeSeconds(event.target.value)}
                      required
                      type="number"
                      value={wakeSeconds}
                    />
                  </Field>
                  <Field label="Model override">
                    <input
                      className="form-input"
                      onChange={(event) => setModel(event.target.value)}
                      placeholder="Default Groq model"
                      value={model}
                    />
                  </Field>
                </div>
                <button className="button-primary w-full" disabled={busy}>
                  {busy ? "Saving…" : "Save supervisor"}
                </button>
              </form>
            </section>

            <section className="panel-card">
              <SectionTitle
                eyebrow="New workflow"
                title="Start an order run"
                detail="The supervisor starts watching as soon as the run is created."
              />
              <form className="space-y-4" onSubmit={handleCreateRun}>
                <Field label="Supervisor">
                  <select
                    className="form-input"
                    onChange={(event) =>
                      setSelectedSupervisorId(event.target.value)
                    }
                    required
                    value={selectedSupervisorId}
                  >
                    <option disabled value="">
                      {supervisors.length
                        ? "Choose a supervisor"
                        : "Create a supervisor first"}
                    </option>
                    {supervisors.map((supervisor) => (
                      <option key={supervisor.id} value={supervisor.id}>
                        {supervisor.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Order ID">
                  <input
                    className="form-input"
                    onChange={(event) => setOrderId(event.target.value)}
                    placeholder="ORD-1042"
                    required
                    value={orderId}
                  />
                </Field>
                <Field label="Order context (JSON)">
                  <textarea
                    className="form-input min-h-28 resize-y font-mono text-xs"
                    onChange={(event) => setOrderContext(event.target.value)}
                    value={orderContext}
                  />
                </Field>
                <button
                  className="button-primary w-full"
                  disabled={busy || !supervisors.length}
                >
                  {busy ? "Starting…" : "Start order run"}
                </button>
              </form>
            </section>

            <section className="panel-card">
              <div className="mb-4 flex items-center justify-between">
                <SectionTitle eyebrow="Work queue" title="Order runs" />
                <span className="count-pill">{runs.length}</span>
              </div>
              {initialLoad ? (
                <p className="text-sm text-slate-500">Loading runs…</p>
              ) : runs.length ? (
                <div className="max-h-[460px] space-y-2 overflow-auto pr-1">
                  {runs.map((run) => (
                    <button
                      aria-pressed={run.id === selectedRunId}
                      className={`run-list-item ${
                        run.id === selectedRunId ? "run-list-item-selected" : ""
                      }`}
                      key={run.id}
                      onClick={() => chooseRun(run.id)}
                      type="button"
                    >
                      <div className="flex min-w-0 items-center justify-between gap-3">
                        <span className="truncate text-sm font-semibold text-slate-800">
                          {run.order_id}
                        </span>
                        <StatusBadge status={run.status} />
                      </div>
                      <p className="mt-1 truncate text-xs text-slate-500">
                        Updated {formatDate(run.updated_at)}
                      </p>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="rounded-lg bg-slate-50 px-3 py-4 text-sm text-slate-500">
                  No runs yet. Create a supervisor and start the first order.
                </p>
              )}
            </section>
          </aside>

          <section className="min-w-0">
            {selectedRun ? (
              <RunWorkspace
                busy={busy}
                eventPayload={eventPayload}
                eventType={eventType}
                instruction={instruction}
                onEventPayloadChange={setEventPayload}
                onEventTypeChange={setEventType}
                onInstructionChange={setInstruction}
                onRunControl={runControl}
                onSubmitEvent={submitEvent}
                onSubmitInstruction={submitInstruction}
                run={selectedRun}
              />
            ) : (
              <div className="panel-card grid min-h-80 place-items-center text-center">
                <div className="max-w-sm">
                  <div className="mx-auto grid size-12 place-items-center rounded-2xl bg-emerald-50 text-lg font-semibold text-emerald-900">
                    ↗
                  </div>
                  <h2 className="mt-4 text-lg font-semibold text-slate-900">
                    {initialLoad ? "Connecting to your workspace…" : "Ready when you are"}
                  </h2>
                  <p className="mt-2 text-sm leading-6 text-slate-500">
                    {runs.length
                      ? "Select an order run from the work queue to inspect its timeline and controls."
                      : "Create a supervisor, then start an order run to see its live activity here."}
                  </p>
                </div>
              </div>
            )}
          </section>
        </div>

        <footer className="mt-8 flex flex-col justify-between gap-2 border-t border-slate-200 pt-5 text-xs text-slate-500 sm:flex-row">
          <span>Order Supervisor · Local operator workspace</span>
          <span>Tools simulate side effects; no external commerce actions are sent.</span>
        </footer>
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3">
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      <p className="mt-1 text-xs text-emerald-100/70">{label}</p>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-semibold text-slate-600">{label}</span>
      {children}
    </label>
  );
}

function RunWorkspace({
  run,
  busy,
  eventType,
  eventPayload,
  instruction,
  onRunControl,
  onEventTypeChange,
  onEventPayloadChange,
  onInstructionChange,
  onSubmitEvent,
  onSubmitInstruction,
}: {
  run: RunDetail;
  busy: boolean;
  eventType: string;
  eventPayload: string;
  instruction: string;
  onRunControl: (
    control: "pause" | "resume" | "interrupt" | "terminate",
  ) => void;
  onEventTypeChange: (value: string) => void;
  onEventPayloadChange: (value: string) => void;
  onInstructionChange: (value: string) => void;
  onSubmitEvent: (event: FormEvent<HTMLFormElement>) => void;
  onSubmitInstruction: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const active = isActive(run);
  return (
    <div className="space-y-5">
      <section className="panel-card">
        <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-start">
          <div className="min-w-0">
            <p className="eyebrow">Selected order</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
                {run.order_id}
              </h2>
              <StatusBadge status={run.status} />
            </div>
            <p className="mt-2 break-all text-xs text-slate-400">
              Run ID · {run.id}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              {run.sleep_until
                ? `Next scheduled wake · ${formatDate(run.sleep_until)}`
                : "No scheduled wake"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {run.status === "paused" ? (
              <button
                className="button-primary"
                disabled={busy}
                onClick={() => onRunControl("resume")}
                type="button"
              >
                Resume
              </button>
            ) : (
              <button
                className="button-secondary"
                disabled={busy || !active}
                onClick={() => onRunControl("pause")}
                type="button"
              >
                Pause
              </button>
            )}
            <button
              className="button-secondary"
              disabled={busy || !active}
              onClick={() => onRunControl("interrupt")}
              type="button"
            >
              Interrupt
            </button>
            <button
              className="button-danger"
              disabled={busy || !active}
              onClick={() => onRunControl("terminate")}
              type="button"
            >
              Terminate
            </button>
          </div>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="panel-card">
          <SectionTitle
            eyebrow="Operator input"
            title="Inject an order event"
            detail="Urgent event types can wake the agent immediately."
          />
          <form className="space-y-4" onSubmit={onSubmitEvent}>
            <Field label="Event type">
              <select
                className="form-input"
                onChange={(event) => onEventTypeChange(event.target.value)}
                value={eventType}
              >
                {eventTypes.map((type) => (
                  <option key={type} value={type}>
                    {readable(type)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Payload (JSON)">
              <textarea
                className="form-input min-h-24 resize-y font-mono text-xs"
                onChange={(event) => onEventPayloadChange(event.target.value)}
                value={eventPayload}
              />
            </Field>
            <button className="button-primary" disabled={busy || !active}>
              Send event
            </button>
          </form>
        </section>

        <section className="panel-card">
          <SectionTitle
            eyebrow="Human guidance"
            title="Add a run instruction"
            detail="It will be included the next time the agent runs."
          />
          <form className="space-y-4" onSubmit={onSubmitInstruction}>
            <Field label="Instruction">
              <textarea
                className="form-input min-h-24 resize-y"
                maxLength={4000}
                onChange={(event) => onInstructionChange(event.target.value)}
                placeholder="For this order, escalate any shipment delay."
                required
                value={instruction}
              />
            </Field>
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-slate-400">
                {instruction.length}/4000 characters
              </span>
              <button className="button-primary" disabled={busy || !active}>
                Save instruction
              </button>
            </div>
          </form>
          {run.extra_instructions.length ? (
            <div className="mt-4 space-y-2 border-t border-slate-100 pt-4">
              {run.extra_instructions.map((text, index) => (
                <p
                  className="rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950"
                  key={`${index}-${text}`}
                >
                  {text}
                </p>
              ))}
            </div>
          ) : null}
        </section>
      </div>

      <section className="panel-card">
        <SectionTitle eyebrow="Run memory" title="Supervisor summary" />
        <p className="text-sm leading-6 text-slate-600">
          {run.memory_summary || "The agent has not stored any run memory yet."}
        </p>
      </section>

      {run.final_output ? (
        <section className="panel-card border-emerald-200 bg-emerald-50/60">
          <SectionTitle eyebrow="Run outcome" title="Final report" />
          <div className="grid gap-4 sm:grid-cols-2">
            <OutputBlock label="Summary" value={run.final_output.summary} />
            <OutputBlock label="Key learnings" value={run.final_output.learnings} />
            <OutputBlock label="Feedback" value={run.final_output.feedback} />
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Important actions
              </p>
              {run.final_output.important_actions.length ? (
                <pre className="mt-2 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-700">
                  {JSON.stringify(run.final_output.important_actions, null, 2)}
                </pre>
              ) : (
                <p className="mt-2 text-sm text-slate-500">No actions reported.</p>
              )}
            </div>
          </div>
        </section>
      ) : null}

      <section className="panel-card">
        <div className="mb-5 flex items-end justify-between gap-3">
          <SectionTitle
            eyebrow="Audit trail"
            title="Run timeline"
            detail="Updates automatically every five seconds."
          />
          <span className="count-pill">{run.timeline.length} entries</span>
        </div>
        {run.timeline.length ? (
          <ol className="timeline-list">
            {[...run.timeline].reverse().map((entry) => (
              <TimelineItem entry={entry} key={entry.id} />
            ))}
          </ol>
        ) : (
          <p className="rounded-lg bg-slate-50 px-3 py-4 text-sm text-slate-500">
            No activity recorded yet. The workflow will add its first wake entry
            after the initial agent run.
          </p>
        )}
      </section>
    </div>
  );
}

function OutputBlock({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className="mt-2 text-sm leading-6 text-slate-700">
        {value || "No report available."}
      </p>
    </div>
  );
}

function TimelineItem({ entry }: { entry: TimelineEntry }) {
  return (
    <li className="timeline-entry">
      <div className="timeline-marker" />
      <div className="min-w-0 flex-1 pb-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-semibold capitalize text-slate-800">
            {readable(entry.type)}
          </p>
          <time className="text-[11px] text-slate-400">
            {formatDate(entry.created_at)}
          </time>
        </div>
        <p className="mt-1 text-xs capitalize text-slate-500">
          {readable(entry.kind)}
        </p>
        {Object.keys(entry.payload).length ? (
          <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-[11px] leading-5 text-slate-600">
            {JSON.stringify(entry.payload, null, 2)}
          </pre>
        ) : null}
      </div>
    </li>
  );
}
