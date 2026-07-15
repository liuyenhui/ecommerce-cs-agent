# Decision Status Badges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw decision enums and oversized trace timeline buttons with localized, accessible, compact badges while preserving node-detail selection.

**Architecture:** Extend the shared decision presentation layer with pure badge models, then render those models in the Customer Admin chat bubble. Extract node status/progress presentation into a second pure helper used by the shared `DecisionTraceReplay`, so Customer Admin and System Admin receive the same localized behavior without changing API contracts.

**Tech Stack:** React 19, TypeScript, Vitest, Node test runner, shared Carbon-style CSS, X6 trace replay.

---

## File Structure

- Modify `admin-web/shared/trace-presentation.ts`: produce localized action, risk, and status badge models while preserving raw values.
- Modify `admin-web/shared/trace-presentation.test.ts`: verify labels, semantic tones, unknown-value fallback, and raw-value retention.
- Create `admin-web/shared/trace-node-presentation.ts`: derive localized node state, tone, current-state text, and completed progress.
- Create `admin-web/shared/trace-node-presentation.test.ts`: test current/completed/waiting/skipped/failed nodes and progress counts.
- Modify `admin-web/customer-admin/src/App.tsx`: render badge models in AI chat messages instead of `动作 candidate · 风险 low`.
- Modify `admin-web/customer-admin/src/styles.css`: style compact message badges using existing Admin colors and visible focus-safe layout.
- Modify `admin-web/shared/trace-replay.tsx`: render the node selector as accessible compact badges with progress.
- Modify `admin-web/shared/styles/base.css`: replace grid-card timeline styling with wrapping node badges and mobile overflow protection.
- Modify `admin-web/scripts/assert-ui-regressions.mjs`: guard localized chat badges, raw-value titles, node buttons, and `aria-pressed`.
- Modify `admin-web/src/mobile-shell.test.mjs`: guard wrapping node badges and the absence of horizontal scrolling rules.
- Modify `admin-web/package.json`: include the new pure helper test in the default Admin test gate.

### Task 1: Shared decision badge presentation

**Files:**
- Modify: `admin-web/shared/trace-presentation.ts`
- Modify: `admin-web/shared/trace-presentation.test.ts`

- [ ] **Step 1: Write the failing badge presentation tests**

Add imports and tests that define the public model:

```typescript
import { decisionStatuses, presentDecisionBadges, presentDecisionTrace } from "./trace-presentation";

it("builds localized badges while retaining raw values", () => {
  expect(presentDecisionBadges({
    action: "candidate",
    status: "candidate",
    risk: "low"
  })).toEqual([
    { key: "action", label: "建议回复", raw: "candidate", tone: "info" },
    { key: "risk", label: "低风险", raw: "low", tone: "success" },
    { key: "status", label: "等待人工确认", raw: "candidate", tone: "warning" }
  ]);
});

it("does not expose unknown backend enums as visible badge text", () => {
  expect(presentDecisionBadges({ action: "new_action", status: "new_status", risk: "new_risk" }))
    .toEqual([
      { key: "action", label: "未知动作", raw: "new_action", tone: "neutral" },
      { key: "risk", label: "未知风险", raw: "new_risk", tone: "neutral" },
      { key: "status", label: "未知状态", raw: "new_status", tone: "neutral" }
    ]);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
npm --prefix admin-web exec -- vitest run --root . shared/trace-presentation.test.ts
```

Expected: FAIL because `presentDecisionBadges` is not exported.

- [ ] **Step 3: Implement the minimal badge model**

Add these exported types and function beside `presentDecisionTrace`:

```typescript
export type DecisionBadgeTone = "info" | "success" | "warning" | "danger" | "neutral";

export type DecisionBadge = {
  key: "action" | "risk" | "status";
  label: string;
  raw: string;
  tone: DecisionBadgeTone;
};

export function presentDecisionBadges(input: TracePresentationInput): DecisionBadge[] {
  const action = normalized(input.action);
  const status = normalized(input.status);
  const risk = normalized(input.risk);
  const presentation = presentDecisionTrace(input);
  const statusLabels: Record<string, string> = { candidate: "等待人工确认" };

  return [
    action ? { key: "action", label: action === "candidate" ? "建议回复" : actionLabels[action] || "未知动作", raw: action, tone: actionTone(action) } : null,
    risk ? { key: "risk", label: riskLabels[risk] || "未知风险", raw: risk, tone: riskTone(risk) } : null,
    status ? { key: "status", label: statusLabels[status] || presentation.statusLabel, raw: status, tone: statusTone(status) } : null
  ].filter((item): item is DecisionBadge => Boolean(item));
}
```

Implement `actionTone`, `riskTone`, and `statusTone` as deterministic mappings: safe/complete → `success`, waiting/candidate/retrying → `warning`, failed/handoff/high → `danger`, known action → `info`, unknown → `neutral`.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the same Vitest command. Expected: all `trace-presentation.test.ts` tests pass.

- [ ] **Step 5: Commit**

```bash
git add admin-web/shared/trace-presentation.ts admin-web/shared/trace-presentation.test.ts
git commit -m "feat: present localized decision badges"
```

### Task 2: Customer chat message badges

**Files:**
- Modify: `admin-web/customer-admin/src/App.tsx`
- Modify: `admin-web/customer-admin/src/styles.css`
- Modify: `admin-web/scripts/assert-ui-regressions.mjs`

- [ ] **Step 1: Add failing UI regression guards**

Extend `assert-ui-regressions.mjs` with checks that require `presentDecisionBadges`, `decisionBadges`, `title={badge.raw}`, and forbid the old raw string renderer:

```javascript
['AI chat renders localized decision badges with raw values only in titles',
  messageHistory.includes('presentDecisionBadges') &&
  messageHistory.includes('decisionBadges') &&
  messageHistory.includes('title={badge.raw}') &&
  styles.includes('.decisionBadge') &&
  !messageHistory.includes('`动作 ${trace.action}`') &&
  !messageHistory.includes('`风险 ${trace.risk_level}`')],
```

- [ ] **Step 2: Run the guard and verify RED**

Run:

```bash
node admin-web/scripts/assert-ui-regressions.mjs
```

Expected: FAIL on the new localized decision badge check.

- [ ] **Step 3: Render React badge content in `ChatBubble`**

Import `presentDecisionBadges`, change `meta?: string` to `meta?: React.ReactNode`, replace `decisionMeta` with:

```tsx
function decisionBadges(trace: CustomerTrace) {
  return (
    <span className="decisionBadges" aria-label="本次 AI 决策摘要">
      {presentDecisionBadges({ action: trace.action, status: trace.status, risk: trace.risk_level }).map((badge) => (
        <span key={badge.key} className={`decisionBadge ${badge.tone}`} title={badge.raw}>
          {badge.label}
        </span>
      ))}
    </span>
  );
}
```

Pass `meta={decisionBadges(trace)}` to the AI bubble. In `ChatBubble`, render `{meta}` directly instead of wrapping it in `<small>`.

- [ ] **Step 4: Add compact Carbon-style message badge CSS**

Add:

```css
.decisionBadges { display:flex; flex-wrap:wrap; gap:6px; }
.decisionBadge { display:inline-flex; align-items:center; min-height:24px; padding:2px 9px; border:1px solid #a8b8ca; border-radius:999px; background:#fff; color:#334155; font-size:12px; font-weight:720; white-space:nowrap; }
.decisionBadge.info { border-color:#78a9ff; background:#edf5ff; color:#0043ce; }
.decisionBadge.success { border-color:#42be65; background:#defbe6; color:#0e6027; }
.decisionBadge.warning { border-color:#d2a106; background:#fff8db; color:#684e00; }
.decisionBadge.danger { border-color:#fa4d56; background:#fff1f1; color:#a2191f; }
.decisionBadge.neutral { border-color:#c6c6c6; background:#f4f4f4; color:#525252; }
```

- [ ] **Step 5: Run focused guards and Admin TypeScript**

```bash
node admin-web/scripts/assert-ui-regressions.mjs
npm --prefix admin-web exec -- tsc --noEmit
```

Expected: UI guard passes and TypeScript reports no errors.

- [ ] **Step 6: Commit**

```bash
git add admin-web/customer-admin/src/App.tsx admin-web/customer-admin/src/styles.css admin-web/scripts/assert-ui-regressions.mjs
git commit -m "feat: show readable decision badges in chat"
```

### Task 3: Accessible trace node badges and progress

**Files:**
- Create: `admin-web/shared/trace-node-presentation.ts`
- Create: `admin-web/shared/trace-node-presentation.test.ts`
- Modify: `admin-web/shared/trace-replay.tsx`
- Modify: `admin-web/shared/styles/base.css`
- Modify: `admin-web/scripts/assert-ui-regressions.mjs`
- Modify: `admin-web/src/mobile-shell.test.mjs`
- Modify: `admin-web/package.json`

- [ ] **Step 1: Write failing pure node presentation tests**

Create tests for visible state and progress:

```typescript
import { describe, expect, it } from "vitest";
import { presentTraceNode, summarizeTraceProgress } from "./trace-node-presentation";

describe("trace node badges", () => {
  it.each([
    ["completed", false, "已完成", "done"],
    ["running", true, "当前 · 处理中", "current"],
    ["pending", false, "等待中", "pending"],
    ["skipped", false, "已跳过", "skipped"],
    ["failed", false, "处理失败", "failed"]
  ])("presents %s", (status, current, label, tone) => {
    expect(presentTraceNode(status, current)).toMatchObject({ label, tone });
  });

  it("counts completed nodes without treating skipped nodes as completed", () => {
    expect(summarizeTraceProgress([{ status: "completed" }, { status: "completed" }, { status: "skipped" }]))
      .toEqual({ completed: 2, total: 3, label: "2 / 3 已完成" });
  });
});
```

- [ ] **Step 2: Add the test to `admin-web/package.json` and verify RED**

Add `shared/trace-node-presentation.test.ts` to the Vitest file list in `scripts.test`, then run:

```bash
npm --prefix admin-web test
```

Expected: FAIL because `trace-node-presentation.ts` does not exist.

- [ ] **Step 3: Implement the pure helper**

Create `presentTraceNode(rawStatus, current)` returning `{ label, tone, raw }`, where `tone` is `done | current | pending | skipped | failed`. Create `summarizeTraceProgress(nodes)` that counts only `completed` nodes and returns the exact progress label.

- [ ] **Step 4: Replace the timeline markup**

In `DecisionTraceReplay`, compute progress from `graphData.nodes`, change the list to:

```tsx
<div className="traceNodeNavigationHeader">
  <strong>处理步骤</strong>
  <span>{progress.label}</span>
</div>
<ol className="traceNodeBadges" aria-label="处理步骤">
  {graphData.nodes.map((node) => {
    const selected = node.id === selectedNode?.id;
    const nodePresentation = presentTraceNode(node.status, node.id === currentNodeId);
    return (
      <li key={node.id}>
        <button
          type="button"
          className={nodePresentation.tone}
          aria-pressed={selected}
          title={`${node.id} · ${nodePresentation.raw}`}
          onClick={() => handleSelectNode(node.id)}
        >
          <span className="traceNodeDot" aria-hidden="true" />
          <strong>{businessNodeLabel(node.id)}</strong>
          <span>{nodePresentation.label}</span>
        </button>
      </li>
    );
  })}
</ol>
```

Keep `describeNodeBlocker` in the node detail panel rather than expanding badge height with blocker prose.

- [ ] **Step 5: Replace timeline CSS with wrapping badge CSS**

Use flex wrapping, 34px minimum height, pill borders, `aria-pressed` focus/selection styling, and state-specific dot/text colors. Remove the old `min-height:58px`, grid columns, and `overflow-wrap:anywhere`. On mobile keep `display:flex; flex-wrap:wrap; width:100%; overflow-x:hidden` and do not collapse each badge to a full-width row.

- [ ] **Step 6: Add UI and mobile regression guards**

Require `traceNodeBadges`, `traceNodeNavigationHeader`, `aria-pressed={selected}`, localized state copy, `flex-wrap: wrap`, and `overflow-x: hidden`. Forbid the old `.traceTimeline` grid and `min-height: 58px` rules.

- [ ] **Step 7: Run focused tests and guards**

```bash
npm --prefix admin-web exec -- vitest run --root . shared/trace-node-presentation.test.ts shared/trace-presentation.test.ts
node admin-web/scripts/assert-ui-regressions.mjs
node --test admin-web/src/mobile-shell.test.mjs
```

Expected: all tests and guards pass.

- [ ] **Step 8: Commit**

```bash
git add admin-web/shared/trace-node-presentation.ts admin-web/shared/trace-node-presentation.test.ts admin-web/shared/trace-replay.tsx admin-web/shared/styles/base.css admin-web/scripts/assert-ui-regressions.mjs admin-web/src/mobile-shell.test.mjs admin-web/package.json
git commit -m "feat: replace trace timeline with node badges"
```

### Task 4: Full verification and visual QA

**Files:**
- Modify only if verification exposes a defect in the files listed above.

- [ ] **Step 1: Run the complete Admin test gate**

```bash
npm --prefix admin-web test
```

Expected: TypeScript, Vitest, boundary tests, UI regression guards, mobile tests, and landing tests all pass.

- [ ] **Step 2: Build both Admin entrypoints**

```bash
npm --prefix admin-web run build
```

Expected: customer and system Vite builds complete successfully.

- [ ] **Step 3: Run repository-wide regression tests**

```bash
.venv/bin/pytest -q
```

Expected: all Python tests pass; the existing Starlette/httpx deprecation warning is acceptable.

- [ ] **Step 4: Inspect desktop and mobile states**

Run Customer Admin locally or deploy the branch preview, then inspect the same simulated message at `1440x900` and `390x844`. Confirm:

- no raw `candidate` or `low` appears in visible chat text;
- badges wrap without overlap or horizontal scrolling;
- current and completed node states remain distinguishable without color;
- clicking a node updates the node detail panel;
- Customer Admin calls only `/v1/admin/auth/me` and has no System Admin entry.

- [ ] **Step 5: Run final hygiene checks**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and only intentional files are modified.

- [ ] **Step 6: Commit verification fixes if needed**

If Step 4 exposes a defect, add only the corrected implementation/test files and commit:

```bash
git add admin-web
git commit -m "fix: polish decision badge responsiveness"
```

If no defect is found, do not create an empty commit.
