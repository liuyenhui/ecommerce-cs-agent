import { describe, expect, it } from "vitest";
import { scrollBehaviorForReducedMotion } from "./landing-motion";

describe("scrollBehaviorForReducedMotion", () => {
  it("uses immediate scrolling when reduced motion is requested", () => {
    expect(scrollBehaviorForReducedMotion(true)).toBe("auto");
  });

  it("keeps smooth scrolling when motion is allowed", () => {
    expect(scrollBehaviorForReducedMotion(false)).toBe("smooth");
  });
});
