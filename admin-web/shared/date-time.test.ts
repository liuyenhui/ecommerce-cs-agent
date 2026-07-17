import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { renderCell } from "./data";

const markup = (node: React.ReactNode) => renderToStaticMarkup(React.createElement(React.Fragment, null, node));

describe("Admin Shanghai time display", () => {
  it("formats UTC timestamps as Chinese Shanghai time across a day boundary", () => {
    const html = markup(renderCell("2026-07-17T16:30:45Z", "created_at"));

    expect(html).toContain("2026年7月18日 00:30:45");
    expect(html).not.toContain("2026-07-17T16:30:45Z");
  });

  it("uses the standard empty marker for invalid timestamp values", () => {
    expect(markup(renderCell("invalid", "updated_at"))).toContain("—");
    expect(markup(renderCell(null, "timestamp"))).toContain("—");
  });

  it("does not reinterpret ordinary identifiers as timestamps", () => {
    expect(markup(renderCell("2026-07-17T16:30:45Z", "decision_id"))).toContain("2026-07-17T16:30:45Z");
  });
});
