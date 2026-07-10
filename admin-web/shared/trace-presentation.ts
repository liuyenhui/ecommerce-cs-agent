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

const actionLabels: Record<string, string> = {
  context_request: "等待补充资料",
  action_request: "等待外部操作",
  handoff: "转人工处理",
  auto_reply: "可以安全回复",
  answer_ready: "可以安全回复",
  candidate: "建议回复待确认"
};

const statusLabels: Record<string, string> = {
  waiting_context: "等待补充资料",
  context_request: "等待补充资料",
  action_request: "等待外部操作",
  handoff: "转人工处理",
  auto_reply: "可以安全回复",
  answer_ready: "可以安全回复",
  candidate: "建议回复待确认"
};

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
  const statusLabel = statusLabels[status] || actionLabels[action] || status || "未知状态";

  if (status === "waiting_context" || action === "context_request") {
    const labels = Array.from(new Set(missingContext.map((item) => contextLabels[item] || `${item}资料`)));
    return {
      actionLabel,
      statusLabel,
      riskLabel: riskLabels[risk] || risk || "未知风险",
      currentNodeId: "context_gate",
      title: "等待补充资料",
      explanation: labels.length
        ? `缺少${labels.join("、")}，补充后 AI 才能继续判断。`
        : "缺少商品、订单、物流或规则资料，补充后 AI 才能继续判断。"
    };
  }

  if (status === "action_request" || action === "action_request") {
    return buildPresentation(actionLabel, statusLabel, risk, "action_gate", "等待外部操作", "需要外部系统完成操作并回传结果，AI 才能继续处理。");
  }
  if (status === "handoff" || action === "handoff") {
    return buildPresentation(actionLabel, statusLabel, risk, "policy_gate", "转人工处理", "风险或业务规则要求人工介入，本次不会自动回复。");
  }
  if (["answer_ready", "auto_reply"].includes(status) || ["answer_ready", "auto_reply"].includes(action)) {
    return buildPresentation(actionLabel, statusLabel, risk, "policy_gate", "可以安全回复", "资料与规则检查已通过，可以安全生成或发送回复。");
  }
  if (status === "candidate" || action === "candidate") {
    return buildPresentation(actionLabel, statusLabel, risk, "policy_gate", "建议回复待确认", "AI 已生成建议回复，等待确认后再发送。");
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
