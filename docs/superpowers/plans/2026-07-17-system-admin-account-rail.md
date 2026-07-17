# System Admin Account Rail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the authenticated System Admin account summary from the page content into the bottom of the left navigation rail.

**Architecture:** Add an optional `railFooter` slot to the shared `AdminFrame`, pass the existing session-backed `SystemUserSummary` from the System Admin app, and simplify `SystemWorkspace` to a single content column. CSS owns collapsed and mobile presentation without changing authentication behavior.

**Tech Stack:** React, TypeScript, CSS, Vitest, Testing Library

---

### Task 1: Lock the layout behavior with tests

**Files:**
- Modify: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] Add a test rendering the authenticated app and assert the account summary is inside `.rail`, outside `.systemWorkspace`, and uses the existing session values.
- [ ] Run `npm --prefix admin-web test -- system-admin/src/system-admin.test.tsx` and confirm the new assertion fails because the summary is still inside the workspace.

### Task 2: Move the summary into the rail

**Files:**
- Modify: `admin-web/shared/components.tsx`
- Modify: `admin-web/system-admin/src/App.tsx`
- Modify: `admin-web/system-admin/src/SystemWorkspace.tsx`
- Modify: `admin-web/system-admin/src/styles.css`
- Modify: `admin-web/shared/styles/base.css`

- [ ] Add optional `railFooter?: React.ReactNode` to `AdminFrame` and render it after the rail collapse control.
- [ ] Pass `SystemUserSummary` through `railFooter` in the authenticated System Admin app.
- [ ] Remove the session prop and right-side account aside from `SystemWorkspace`.
- [ ] Make `.systemWorkspace` a single-column container and style the rail footer for expanded, collapsed, and mobile navigation.
- [ ] Re-run the focused test and confirm it passes.

### Task 3: Regression and release documentation

**Files:**
- Modify: `docs/system-admin-design.md`
- Modify: `docs/development-handoff.md`

- [ ] Document the account-summary placement without changing session or API ownership.
- [ ] Run `npm test && npm run build:system` and confirm all checks pass.
- [ ] Commit, push, open a PR, wait for required checks, merge, publish images, deploy through GitOps, and verify System Admin health and the new live asset.

