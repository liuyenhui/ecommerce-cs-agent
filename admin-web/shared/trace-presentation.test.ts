import { describe, expect, it } from "vitest";
import { presentDecisionTrace } from "./trace-presentation";

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
});
