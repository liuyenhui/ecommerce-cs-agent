import { describe, expect, it, vi } from "vitest";
import {
  buildCanonicalSimulationTrace,
  isCurrentOperation,
  requireReloadedSimulation
} from "./simulation-workflow";

describe("requireReloadedSimulation", () => {
  it("rejects when message history reload fails after simulation creation", async () => {
    await expect(requireReloadedSimulation(
      () => Promise.reject(new Error("GET message-traces failed")),
      "decision-001"
    )).rejects.toThrow("模拟已创建，但会话历史刷新失败，请点击刷新后再查看。输入内容已保留。");
  });

  it("rejects when the successful reload does not contain the new decision", async () => {
    await expect(requireReloadedSimulation(
      () => Promise.resolve([{ decision_id: "decision-old", conversation_id: "conv-old" }]),
      "decision-001"
    )).rejects.toThrow("模拟已创建，但刷新结果中未找到新会话，请点击刷新后再查看。输入内容已保留。");
  });

  it("returns the canonical reloaded trace for the new decision", async () => {
    const reloaded = { decision_id: "decision-001", conversation_id: "sim-conv-001" };
    await expect(requireReloadedSimulation(() => Promise.resolve([reloaded]), "decision-001")).resolves.toBe(reloaded);
  });

  it("rejects an empty decision id before awaiting reload", async () => {
    const reload = vi.fn(() => Promise.resolve([]));
    await expect(requireReloadedSimulation(reload, "")).rejects.toThrow("模拟结果缺少决策编号");
    expect(reload).not.toHaveBeenCalled();
  });

  it("does not apply a delayed store A response after switching to store B", () => {
    const storeA = { storeId: "store-a", generation: 1, requestId: 1 };
    expect(isCurrentOperation(storeA, "store-b", 2, 1)).toBe(false);
  });

  it("does not let an older refresh overwrite a newer request", () => {
    const older = { storeId: "store-a", generation: 1, requestId: 1 };
    expect(isCurrentOperation(older, "store-a", 1, 2)).toBe(false);
  });

  it("does not apply an operation after MessageHistory unmounts", () => {
    const operation = { storeId: "store-a", generation: 1, requestId: 1 };
    expect(isCurrentOperation(operation, "store-a", 1, 1, false)).toBe(false);
  });

  it("keeps GET trace fields authoritative over conflicting POST data", () => {
    const canonical = {
      decision_id: "decision-001",
      conversation_id: "sim-conv-001",
      customer_message: "服务端消息",
      action: "handoff",
      status: "failed",
      risk_level: "high",
      missing_context: ["orders"],
      trace: { graph_version: "server" }
    };

    expect(buildCanonicalSimulationTrace(canonical, "提交内容")).toEqual(canonical);
  });

  it("uses submitted content only when GET omits customer_message", () => {
    expect(buildCanonicalSimulationTrace({ decision_id: "decision-001", action: "handoff" }, "提交内容"))
      .toEqual({ decision_id: "decision-001", action: "handoff", customer_message: "提交内容" });
  });
});
