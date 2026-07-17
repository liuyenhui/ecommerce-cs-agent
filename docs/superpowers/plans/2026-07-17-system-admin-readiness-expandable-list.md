# System Admin Readiness Expandable List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace large readiness cards with a compact, accessible, per-store expandable list while preserving server pagination and readiness semantics.

**Architecture:** `ReadinessPage` owns a `Set<string>` of expanded store IDs and renders one semantic table for store summary rows plus optional detail rows. Existing guidance mapping remains the only fallback for missing impact/next-action text; CSS provides dense desktop columns and labeled mobile blocks.

**Tech Stack:** React, TypeScript, CSS, Vitest, Testing Library

---

### Task 1: Add failing interaction coverage

**Files:**
- Modify: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] Replace the static readiness markup assertion with a rendered interaction test containing two stores and one non-passing check per store.
- [ ] Assert both detail texts are absent initially, each row exposes a button with `aria-expanded="false"`, and exactly one pagination navigation exists.
- [ ] Click the first store button, assert only its reason/impact/next-action appear and `aria-expanded="true"`; click again and assert they disappear.
- [ ] Run `npx vitest run --root . system-admin/src/system-admin.test.tsx` from `admin-web` and confirm failure because the current cards render all details immediately.

### Task 2: Implement the expandable list

**Files:**
- Modify: `admin-web/system-admin/src/pages/ReadinessPage.tsx`
- Modify: `admin-web/system-admin/src/styles.css`

- [ ] Add `expandedStores` state and a toggle that creates a new `Set` when adding or removing a store ID.
- [ ] Render a table named `店铺配置完成度`; summary rows contain the expand button, store ID, tenant ID, status and count from `checks.filter(check => check.status !== "pass")`.
- [ ] Render a following detail row only for expanded stores; place a nested semantic list of non-passing checks in one spanning cell, or the healthy message when the count is zero.
- [ ] Add field labels through `data-label` values and CSS that changes the table rows to labeled blocks below 900px without horizontal overflow.
- [ ] Re-run the focused Vitest command and confirm all System Admin tests pass.

### Task 3: Align documentation and regression guards

**Files:**
- Modify: `docs/system-admin-design.md`
- Modify: `admin-web/scripts/assert-ui-regressions.mjs`

- [ ] Document the default-collapsed per-store list and expanded check detail fields in the configuration-completeness module.
- [ ] Add a static guard requiring the table accessible name, `aria-expanded`, and the readiness detail-row class.
- [ ] Run `npm test && npm run build:system` from `admin-web`; expect all tests, guards and the production build to pass.
- [ ] Run staged diff and sensitive-pattern checks, commit, push, create a ready PR, merge after required checks, publish images, deploy through GitOps, and verify all three live health endpoints plus the new System Admin asset.

