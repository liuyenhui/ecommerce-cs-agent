import { describe, expect, it } from "vitest";
import { requireReloadedSimulation } from "./simulation-workflow";

describe("requireReloadedSimulation", () => {
  it("rejects when message history reload fails after simulation creation", async () => {
    await expect(requireReloadedSimulation(
      Promise.reject(new Error("GET message-traces failed")),
      "decision-001"
    )).rejects.toThrow("模拟已创建，但会话历史刷新失败，请点击刷新后再查看。输入内容已保留。");
  });

  it("rejects when the successful reload does not contain the new decision", async () => {
    await expect(requireReloadedSimulation(
      Promise.resolve([{ decision_id: "decision-old", conversation_id: "conv-old" }]),
      "decision-001"
    )).rejects.toThrow("模拟已创建，但刷新结果中未找到新会话，请点击刷新后再查看。输入内容已保留。");
  });

  it("returns the canonical reloaded trace for the new decision", async () => {
    const reloaded = { decision_id: "decision-001", conversation_id: "sim-conv-001" };
    await expect(requireReloadedSimulation(Promise.resolve([reloaded]), "decision-001")).resolves.toBe(reloaded);
  });
});
