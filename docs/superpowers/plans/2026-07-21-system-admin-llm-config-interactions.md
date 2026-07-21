# System Admin LLM Config Interactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved two-tab System Admin LLM configuration experience with modal editing, masked-key handling, safe deletion, and correct binding-save states.

**Architecture:** Extend the existing `/v1/system-admin/llms` node-configuration boundary with a guarded DELETE operation, keeping reference checks and audit writes in the repository transaction. Refactor the existing React page without changing its API ownership: URL-driven tabs split model management from LangGraph bindings, modal state isolates masked display from replacement input, and a normalized binding snapshot drives dirty/loading behavior.

**Tech Stack:** FastAPI, Pydantic, PostgreSQL, React 18, TypeScript, Vitest/Testing Library, OpenAPI, pytest.

---

### Task 1: Safe LLM deletion API

**Files:**
- Modify: `ecommerce_cs_agent/api/system_admin_llm_nodes.py`
- Modify: `ecommerce_cs_agent/services/llm_node_configuration.py`
- Test: `tests/api/test_system_admin_llm_node_configuration.py`

- [ ] **Step 1: Write failing API tests**

Add tests that create an LLM, delete it with `DELETE /v1/system-admin/llms/{llm_id}`, and assert `204`; bind another LLM and assert delete returns `409` with `error.code=llm_in_use` and reference counts but no model, prompt, message, or secret text. Add read-only-role `403` and unknown-ID `404` coverage.

- [ ] **Step 2: Verify RED**

Run: `/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/pytest -q tests/api/test_system_admin_llm_node_configuration.py -k delete`

Expected: FAIL because DELETE is not registered.

- [ ] **Step 3: Implement repository deletion**

Add `delete_llm(session, llm_id)` to both repositories. In memory, reject IDs present in `bindings.values()` and delete otherwise. In PostgreSQL, lock the model row, query current `langgraph_node_llm_binding` plus protected configuration references, return a sanitized `409 llm_in_use` detail when referenced, otherwise delete `llm_model_config` and write `llm.config.delete` audit in the same transaction.

- [ ] **Step 4: Register DELETE route**

Add `@app.delete(..., status_code=204)` and return an empty `Response(status_code=204)` after repository success. Reuse existing System Admin write-role enforcement.

- [ ] **Step 5: Verify GREEN**

Run the Task 1 test command and expect all selected tests to pass.

### Task 2: OpenAPI deletion contract

**Files:**
- Modify: `docs/openapi.yaml`
- Modify: `tests/contract/test_openapi_contract.py`

- [ ] **Step 1: Write failing contract assertions**

Assert `/v1/system-admin/llms/{llm_id}` exposes DELETE with `204`, `403`, `404`, and `409`, and that the conflict response uses the standard error schema.

- [ ] **Step 2: Verify RED**

Run: `/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/pytest -q tests/contract/test_openapi_contract.py -k llm`

- [ ] **Step 3: Update OpenAPI**

Document safe deletion, reference-conflict behavior, and the rule that response/audit content never contains API Key, prompt, message, or reply bodies.

- [ ] **Step 4: Verify GREEN**

Repeat the Task 2 command and expect PASS.

### Task 3: URL-driven tabs and inline title notes

**Files:**
- Modify: `admin-web/system-admin/src/pages/LlmGovernancePage.tsx`
- Modify: `admin-web/system-admin/src/styles.css`
- Test: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] **Step 1: Write failing UI tests**

Render at `?tab=langgraph`, assert the LangGraph tab/panel is selected and LLM table hidden; click LLM and assert `tab=llms`. Assert each section note is parenthesized and in the same heading row.

- [ ] **Step 2: Verify RED**

Run: `npm --prefix admin-web/system-admin test -- --run -t "LLM tabs"`

- [ ] **Step 3: Implement accessible tabs**

Use `URLSearchParams` with `llms` fallback, `history.replaceState`, `role=tablist`, `aria-selected`, and linked tab panels. Keep unsaved binding state mounted while switching tabs.

- [ ] **Step 4: Style desktop/mobile tabs and heading notes**

Add Carbon-style hairline tabs, compact `.sectionTitleNote`, visible focus, and narrow-screen horizontal tab scrolling without page overflow.

- [ ] **Step 5: Verify GREEN**

Repeat Task 3 tests and expect PASS.

### Task 4: Accessible add/edit modal and masked Key behavior

**Files:**
- Modify: `admin-web/system-admin/src/pages/LlmGovernancePage.tsx`
- Modify: `admin-web/system-admin/src/styles.css`
- Test: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] **Step 1: Write failing modal tests**

Assert edit opens a `dialog`, displays `api_key_masked`, does not include that masked string in PATCH, sends a newly typed Key only when changed, restores focus on cancel, and disables close/save during submission.

- [ ] **Step 2: Verify RED**

Run: `npm --prefix admin-web/system-admin test -- --run -t "LLM modal"`

- [ ] **Step 3: Implement modal state**

Keep `api_key_masked` as read-only display state and `replacementApiKey` as a separate empty input. Build PATCH payload with `api_key` only when replacement input is non-empty. Add dialog focus trapping, Escape/backdrop handling, busy guards, and focus restoration.

- [ ] **Step 4: Verify GREEN**

Repeat Task 4 tests and expect PASS.

### Task 5: Delete UI and binding dirty/loading states

**Files:**
- Modify: `admin-web/system-admin/src/system-api.ts`
- Modify: `admin-web/system-admin/src/pages/LlmGovernancePage.tsx`
- Modify: `admin-web/system-admin/src/styles.css`
- Test: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] **Step 1: Write failing interaction tests**

Assert Delete opens confirmation, `204` removes the row, `409` shows the sanitized binding warning, binding save starts disabled, enables after a select change, shows `保存中…`, rejects duplicate clicks, resets dirty state on success, and remains dirty after failure.

- [ ] **Step 2: Verify RED**

Run: `npm --prefix admin-web/system-admin test -- --run -t "delete LLM|binding dirty"`

- [ ] **Step 3: Add API client and deletion dialog**

Add `deleteLlm(llmId)` using System Admin credentials and render a destructive confirmation dialog. Map `409 llm_in_use` to a warning that instructs the user to unbind or disable the model.

- [ ] **Step 4: Implement normalized binding snapshot**

Store the canonical initial `{node_id: llm_id}` map after load/save, compare sorted entries to selected state, disable save when unchanged or busy, render `保存中…` with `aria-busy`, and preserve selected values on failure.

- [ ] **Step 5: Verify GREEN**

Repeat Task 5 tests and expect PASS.

### Task 6: Documentation and complete verification

**Files:**
- Modify: `docs/development-handoff.md`
- Test: affected frontend, API, contract, and complete repository suites

- [ ] **Step 1: Update handoff**

Add a dated 2026-07-21 entry pointing to the design and plan, documenting two-tab navigation, masked-only Key editing, guarded deletion, and binding dirty/loading behavior.

- [ ] **Step 2: Run affected tests**

Run frontend System Admin tests, `pytest -q tests/api/test_system_admin_llm_node_configuration.py`, and `pytest -q tests/contract`.

- [ ] **Step 3: Run complete verification**

Run `/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/pytest -q`, frontend build/tests, `git diff --check`, and targeted Secret scan required by `AGENTS.md`.

- [ ] **Step 4: Commit implementation**

Stage only scoped files and commit with `feat: improve System Admin LLM configuration`.

- [ ] **Step 5: Push and open PR**

Push `codex/system-admin-llm-config-tabs`, open a ready PR against `main`, and wait for all required checks.

- [ ] **Step 6: Deploy through approved workflows**

After merge approval requirements are satisfied, use `Publish Images`/GitOps rather than local Docker push, update the dev image tag through the repository’s approved deployment workflow, wait for Helm/rollout health, and verify the System Admin host at desktop and mobile sizes. Do not expose credentials or storage state.
