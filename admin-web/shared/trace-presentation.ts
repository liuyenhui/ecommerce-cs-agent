export type TracePresentationInput = {
  action?: unknown;
  status?: unknown;
  risk?: unknown;
  missingContext?: unknown;
};

export type TracePresentation = {
  actionLabel: string;
  statusLabel: string;
  riskLabel: string;
  currentNodeId: string;
  title: string;
  explanation: string;
};

export const decisionStatuses = [
  "received",
  "queued",
  "running",
  "waiting_context",
  "partial_context",
  "ready_to_decide",
  "answer_ready",
  "candidate",
  "action_request",
  "handoff",
  "completed",
  "failed",
  "retrying",
  "canceled"
] as const;

export type DecisionStatus = typeof decisionStatuses[number];

type StatusPresentation = {
  label: string;
  currentNodeId: string;
  title: string;
  explanation: string;
};

const actionLabels: Record<string, string> = {
  context_request: "等待补充资料",
  action_request: "等待外部操作",
  handoff: "转人工处理",
  auto_reply: "可以安全回复",
  answer_ready: "可以安全回复",
  candidate: "建议回复待确认"
};

const statusPresentations = {
  received: { label: "已接收", currentNodeId: "normalize_request", title: "已接收", explanation: "客户咨询已接收，正在准备处理。" },
  queued: { label: "等待处理", currentNodeId: "normalize_request", title: "等待处理", explanation: "咨询已进入处理队列，请稍候。" },
  running: { label: "处理中", currentNodeId: "", title: "处理中", explanation: "AI 正在检索资料并执行规则判断。" },
  waiting_context: { label: "等待补充资料", currentNodeId: "context_gate", title: "等待补充资料", explanation: "缺少商品、订单、物流或规则资料，补充后 AI 才能继续判断。" },
  partial_context: { label: "资料待补齐", currentNodeId: "context_gate", title: "资料待补齐", explanation: "已取得部分资料，仍需补齐缺失内容。" },
  ready_to_decide: { label: "准备决策", currentNodeId: "policy_gate", title: "准备决策", explanation: "资料已准备完成，正在执行回复策略判断。" },
  answer_ready: { label: "可以安全回复", currentNodeId: "policy_gate", title: "可以安全回复", explanation: "资料与规则检查已通过，可以安全生成或发送回复。" },
  candidate: { label: "建议回复待确认", currentNodeId: "policy_gate", title: "建议回复待确认", explanation: "AI 已生成建议回复，等待确认后再发送。" },
  action_request: { label: "等待外部操作", currentNodeId: "action_gate", title: "等待外部操作", explanation: "需要外部系统完成操作并回传结果，AI 才能继续处理。" },
  handoff: { label: "转人工处理", currentNodeId: "policy_gate", title: "转人工处理", explanation: "风险或业务规则要求人工介入，本次不会自动回复。" },
  completed: { label: "处理完成", currentNodeId: "persist_trace", title: "处理完成", explanation: "本次咨询的决策处理已经完成。" },
  failed: { label: "处理失败", currentNodeId: "", title: "处理失败", explanation: "本次处理未完成，请查看安全提示或稍后重试。" },
  retrying: { label: "正在重试", currentNodeId: "", title: "正在重试", explanation: "系统正在重新尝试处理本次咨询。" },
  canceled: { label: "已取消", currentNodeId: "", title: "已取消", explanation: "本次咨询处理已取消，不会自动回复。" }
} satisfies Record<DecisionStatus, StatusPresentation>;

const riskLabels: Record<string, string> = {
  low: "低风险",
  medium: "中风险",
  high: "高风险"
};

const contextLabels: Record<string, string> = {
  product: "商品资料",
  products: "商品资料",
  order: "订单资料",
  orders: "订单资料",
  logistics: "物流资料",
  rule: "规则资料",
  rules: "规则资料"
};

export function presentDecisionTrace(input: TracePresentationInput): TracePresentation {
  const action = normalized(input.action);
  const status = normalized(input.status);
  const risk = normalized(input.risk);
  const missingContext = normalizeList(input.missingContext);
  const actionLabel = actionLabels[action] || action || "未知动作";
  const statusPresentation = isDecisionStatus(status) ? statusPresentations[status] : null;
  const selectedPresentation = statusPresentation || actionFallback(status) || actionFallback(action);
  const statusLabel = selectedPresentation?.label || status || "未知状态";

  if (status === "waiting_context" || (!statusPresentation && action === "context_request")) {
    const labels = Array.from(new Set(missingContext.map((item) => contextLabels[item] || `${item}资料`)));
    return buildPresentation(
      actionLabel,
      statusLabel,
      risk,
      "context_gate",
      "等待补充资料",
      labels.length
        ? `缺少${labels.join("、")}，补充后 AI 才能继续判断。`
        : statusPresentations.waiting_context.explanation
    );
  }

  if (selectedPresentation) {
    return buildPresentation(
      actionLabel,
      statusLabel,
      risk,
      selectedPresentation.currentNodeId,
      selectedPresentation.title,
      selectedPresentation.explanation
    );
  }

  return buildPresentation(actionLabel, statusLabel, risk, "", statusLabel, "请查看下方节点时间线了解处理进度。");
}

function buildPresentation(
  actionLabel: string,
  statusLabel: string,
  risk: string,
  currentNodeId: string,
  title: string,
  explanation: string
): TracePresentation {
  return {
    actionLabel,
    statusLabel,
    riskLabel: riskLabels[risk] || risk || "未知风险",
    currentNodeId,
    title,
    explanation
  };
}

function normalized(value: unknown) {
  return String(value || "").trim().toLowerCase();
}

function normalizeList(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.map(normalized).filter(Boolean);
}

function isDecisionStatus(value: string): value is DecisionStatus {
  return (decisionStatuses as readonly string[]).includes(value);
}

function actionFallback(action: string): StatusPresentation | null {
  const fallbacks: Record<string, StatusPresentation> = {
    context_request: statusPresentations.waiting_context,
    action_request: statusPresentations.action_request,
    handoff: statusPresentations.handoff,
    auto_reply: statusPresentations.answer_ready,
    answer_ready: statusPresentations.answer_ready,
    candidate: statusPresentations.candidate
  };
  return fallbacks[action] || null;
}
