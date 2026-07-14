import { describe, expect, it } from "vitest";
import { presentTraceNode, summarizeTraceProgress } from "./trace-node-presentation";

describe("presentTraceNode", () => {
  it.each([
    ["completed", false, { label: "已完成", tone: "done", raw: "completed" }],
    ["running", true, { label: "当前 · 处理中", tone: "current", raw: "running" }],
    ["pending", false, { label: "等待中", tone: "pending", raw: "pending" }],
    ["skipped", false, { label: "已跳过", tone: "skipped", raw: "skipped" }],
    ["failed", false, { label: "处理失败", tone: "failed", raw: "failed" }]
  ] as const)("maps %s to localized node presentation", (rawStatus, current, expected) => {
    expect(presentTraceNode(rawStatus, current)).toEqual(expected);
  });

  it("lets current state override the raw status tone and prefixes its localized label", () => {
    expect(presentTraceNode("completed", true)).toEqual({
      label: "当前 · 已完成",
      tone: "current",
      raw: "completed"
    });
  });

  it("uses a safe localized fallback while retaining the original raw value", () => {
    expect(presentTraceNode(" Future_State ", false)).toEqual({
      label: "状态未知",
      tone: "pending",
      raw: " Future_State "
    });
  });

  it.each(["constructor", "toString", "__proto__"])("treats prototype key %s as unknown", (rawStatus) => {
    expect(presentTraceNode(rawStatus, false)).toEqual({
      label: "状态未知",
      tone: "pending",
      raw: rawStatus
    });
  });
});

describe("summarizeTraceProgress", () => {
  it("counts only completed nodes and reports every node in the total", () => {
    expect(summarizeTraceProgress([
      { status: "completed" },
      { status: "skipped" },
      { status: "completed" }
    ])).toEqual({ completed: 2, total: 3, label: "2 / 3 已完成" });
  });
});
