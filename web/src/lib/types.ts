export type Supervisor = {
  id: string;
  name: string;
  base_instruction: string;
  available_tools: string[];
  default_wakeup_seconds: number | null;
  model: string | null;
  wake_aggressiveness: string | null;
  created_at: string;
};

export type RunSummary = {
  id: string;
  supervisor_id: string;
  order_id: string;
  status: string;
  sleep_until: string | null;
  created_at: string;
  updated_at: string;
};

export type TimelineEntry = {
  id: string;
  kind: string;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type FinalOutput = {
  summary: string | null;
  important_actions: Record<string, unknown>[];
  learnings: string | null;
  feedback: string | null;
};

export type RunDetail = RunSummary & {
  order_context: Record<string, unknown>;
  extra_instructions: string[];
  timeline: TimelineEntry[];
  memory_summary: string | null;
  final_output: FinalOutput | null;
};

export type Collection<T> = {
  items: T[];
};

export const availableTools = [
  { id: "send_customer_message", label: "Send customer message" },
  { id: "create_internal_note", label: "Create internal note" },
  { id: "mark_order_for_review", label: "Mark order for review" },
] as const;

export const eventTypes = [
  "order_created",
  "payment_confirmed",
  "payment_failed",
  "shipment_created",
  "shipment_delayed",
  "delivered",
  "refund_requested",
  "customer_message_received",
  "no_update_for_n_hours",
] as const;
