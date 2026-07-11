import { describe, expect, it } from "vitest";
import { decisionStatuses, presentDecisionBadges, presentDecisionTrace } from "./trace-presentation";

describe("presentDecisionBadges", () => {
  it("presents candidate decisions as localized badges in a stable order", () => {
    expect(presentDecisionBadges({ action: "candidate", status: "candidate", risk: "low" })).toEqual([
      { key: "action", label: "建议回复", raw: "candidate", tone: "info" },
      { key: "risk", label: "低风险", raw: "low", tone: "success" },
      { key: "status", label: "等待人工确认", raw: "candidate", tone: "warning" }
    ]);
  });

  it("keeps unknown raw values out of visible labels", () => {
    expect(presentDecisionBadges({
      action: "new_action",
      status: "new_status",
      risk: "new_risk"
    })).toEqual([
      { key: "action", label: "未知动作", raw: "new_action", tone: "neutral" },
      { key: "risk", label: "未知风险", raw: "new_risk", tone: "neutral" },
      { key: "status", label: "未知状态", raw: "new_status", tone: "neutral" }
    ]);
  });

  it.each([
    [{ action: "auto_reply", risk: "low", status: "completed" }, ["info", "success", "success"]],
    [{ action: "candidate", risk: "medium", status: "waiting_context" }, ["info", "warning", "warning"]],
    [{ action: "handoff", risk: "high", status: "failed" }, ["danger", "danger", "danger"]],
    [{ action: "action_request", status: "retrying" }, ["info", "warning"]]
  ])("maps known values to semantic tones", (input, expectedTones) => {
    expect(presentDecisionBadges(input).map(({ tone }) => tone)).toEqual(expectedTones);
  });

  it("omits badges whose raw values are empty", () => {
    expect(presentDecisionBadges({ action: " ", status: undefined, risk: "low" })).toEqual([
      { key: "risk", label: "低风险", raw: "low", tone: "success" }
    ]);
  });
});

describe("presentDecisionTrace", () => {
  it.each([
    {
      action: "context_request",
      status: "waiting_context",
      expected: {
        actionLabel: "等待补充资料",
        statusLabel: "等待补充资料",
        currentNodeId: "context_gate",
        title: "等待补充资料"
      }
    },
    {
      action: "action_request",
      status: "action_request",
      expected: {
        actionLabel: "等待外部操作",
        statusLabel: "等待外部操作",
        currentNodeId: "action_gate",
        title: "等待外部操作"
      }
    },
    {
      action: "handoff",
      status: "handoff",
      expected: {
        actionLabel: "转人工处理",
        statusLabel: "转人工处理",
        currentNodeId: "policy_gate",
        title: "转人工处理"
      }
    },
    {
      action: "auto_reply",
      status: "answer_ready",
      expected: {
        actionLabel: "可以安全回复",
        statusLabel: "可以安全回复",
        currentNodeId: "policy_gate",
        title: "可以安全回复"
      }
    },
    {
      action: "candidate",
      status: "candidate",
      expected: {
        actionLabel: "建议回复待确认",
        statusLabel: "建议回复待确认",
        currentNodeId: "policy_gate",
        title: "建议回复待确认"
      }
    }
  ])("maps $status to customer-facing workflow copy", ({ action, status, expected }) => {
    expect(presentDecisionTrace({ action, status })).toMatchObject(expected);
  });

  it.each([
    ["low", "低风险"],
    ["medium", "中风险"],
    ["high", "高风险"]
  ])("maps risk %s to %s", (risk, expected) => {
    expect(presentDecisionTrace({ risk }).riskLabel).toBe(expected);
  });

  it("explains every missing context type in business language", () => {
    const result = presentDecisionTrace({
      action: "context_request",
      status: "waiting_context",
      missingContext: ["products", "orders", "logistics", "rules"]
    });

    expect(result.explanation).toContain("商品资料");
    expect(result.explanation).toContain("订单资料");
    expect(result.explanation).toContain("物流资料");
    expect(result.explanation).toContain("规则资料");
  });

  it("keeps an unresolved waiting-context blocker ahead of a completed persist node", () => {
    expect(presentDecisionTrace({
      action: "context_request",
      status: "waiting_context",
      missingContext: ["products"]
    })).toMatchObject({
      currentNodeId: "context_gate",
      title: "等待补充资料",
      explanation: "缺少商品资料，补充后 AI 才能继续判断。"
    });
  });

  it("localizes a legacy action value passed through the status field", () => {
    expect(presentDecisionTrace({ status: "context_request" })).toMatchObject({
      statusLabel: "等待补充资料",
      title: "等待补充资料"
    });
  });

  it.each([
    ["received", "已接收"],
    ["queued", "等待处理"],
    ["running", "处理中"],
    ["waiting_context", "等待补充资料"],
    ["partial_context", "资料待补齐"],
    ["ready_to_decide", "准备决策"],
    ["answer_ready", "可以安全回复"],
    ["candidate", "建议回复待确认"],
    ["action_request", "等待外部操作"],
    ["handoff", "转人工处理"],
    ["completed", "处理完成"],
    ["failed", "处理失败"],
    ["retrying", "正在重试"],
    ["canceled", "已取消"]
  ])("presents DecisionStatus %s as %s", (status, expectedTitle) => {
    expect(presentDecisionTrace({ status })).toMatchObject({ title: expectedTitle, statusLabel: expectedTitle });
  });

  it("covers every OpenAPI DecisionStatus", () => {
    expect(decisionStatuses).toHaveLength(14);
  });

  it.each([
    ["failed", "candidate", "处理失败"],
    ["canceled", "auto_reply", "已取消"],
    ["retrying", "handoff", "正在重试"],
    ["running", "candidate", "处理中"],
    ["waiting_context", "candidate", "等待补充资料"]
  ])("keeps status %s ahead of conflicting action %s", (status, action, expectedTitle) => {
    expect(presentDecisionTrace({ status, action }).title).toBe(expectedTitle);
  });
});
