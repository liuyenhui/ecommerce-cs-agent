import { describe, expect, it } from "vitest";
import { applySelectedNodeStyles } from "./trace-graph-selection";

describe("applySelectedNodeStyles", () => {
  it("uses the latest selection when import finishes after selection changed", () => {
    const attrs = new Map<string, Record<string, unknown>>();
    const views = [
      { id: "context_gate", stroke: "red" },
      { id: "persist_trace", stroke: "green" }
    ];
    let latestSelection = "context_gate";
    latestSelection = "persist_trace";

    applySelectedNodeStyles(views, latestSelection, (id) => ({
      attr(path: string, value: unknown) {
        attrs.set(id, { ...(attrs.get(id) || {}), [path]: value });
      }
    }));

    expect(attrs.get("persist_trace")).toMatchObject({ "body/stroke": "#0f172a", "body/strokeWidth": 3 });
    expect(attrs.get("context_gate")).toMatchObject({ "body/stroke": "red", "body/strokeWidth": 2 });
  });
});
