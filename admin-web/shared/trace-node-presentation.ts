export type TraceNodeTone = "done" | "current" | "pending" | "skipped" | "failed";

export type TraceNodePresentation = {
  label: string;
  tone: TraceNodeTone;
  raw: string;
};

const traceNodeStates: Record<string, Omit<TraceNodePresentation, "raw">> = Object.create(null);
Object.assign(traceNodeStates, {
  completed: { label: "已完成", tone: "done" },
  running: { label: "处理中", tone: "current" },
  pending: { label: "等待中", tone: "pending" },
  skipped: { label: "已跳过", tone: "skipped" },
  failed: { label: "处理失败", tone: "failed" }
});

export function presentTraceNode(rawStatus: unknown, current: boolean): TraceNodePresentation {
  const raw = String(rawStatus ?? "");
  const normalized = raw.trim().toLowerCase();
  const state = Object.hasOwn(traceNodeStates, normalized)
    ? traceNodeStates[normalized]
    : { label: "状态未知", tone: "pending" as const };

  return {
    label: current ? `当前 · ${state.label}` : state.label,
    tone: current ? "current" : state.tone,
    raw
  };
}

export function summarizeTraceProgress(nodes: Array<{ status?: unknown }>) {
  const completed = nodes.filter((node) => String(node.status ?? "").trim().toLowerCase() === "completed").length;
  const total = nodes.length;
  return { completed, total, label: `${completed} / ${total} 已完成` };
}
