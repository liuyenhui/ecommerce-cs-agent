import { describe, expect, it } from "vitest";
import { reduceGraphUiState } from "./trace-graph-state";

describe("reduceGraphUiState", () => {
  it("hides a failed graph, retries the same trace, and clears fallback after success", () => {
    const failed = reduceGraphUiState({ unavailable: false, retryKey: 0 }, { type: "failed" });
    expect(failed).toEqual({ unavailable: true, retryKey: 0 });

    const retrying = reduceGraphUiState(failed, { type: "retry" });
    expect(retrying).toEqual({ unavailable: false, retryKey: 1 });

    expect(reduceGraphUiState(retrying, { type: "available" }))
      .toEqual({ unavailable: false, retryKey: 1 });
  });

  it("resets fallback for a new trace", () => {
    expect(reduceGraphUiState({ unavailable: true, retryKey: 3 }, { type: "reset" }))
      .toEqual({ unavailable: false, retryKey: 0 });
  });
});
