# ACS Node-Bound Grounded Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the active `generate_candidate` LangGraph node binding perform fact-safe grounded rewrites and make live simulation require that model evidence.

**Architecture:** `NodeBoundReplyProvider.rewrite_grounded()` resolves the existing `generate_candidate` binding, builds the shared safe rewrite messages, invokes the existing OpenAI-compatible provider through a message-level method, and validates the reply before returning it. Any resolution, provider, input, or validation failure returns the deterministic draft with explicit safe metadata; eval accepts successful `node_binding` evidence and continues rejecting deterministic fallback.

**Tech Stack:** Python, pytest, existing OpenAI-compatible HTTP provider, LangGraph node configuration, ACS simulation eval.

---

### Task 1: Node-bound grounded rewrite

**Files:**
- Modify: `tests/services/test_reply_llm.py`
- Modify: `ecommerce_cs_agent/services/llm.py`

- [ ] Add focused tests proving `generate_candidate` resolution, shared safe messages, actual model ID metadata, rejected unsafe output, failed provider output, and metadata-only `last_invocation`.
- [ ] Run the focused tests and confirm they fail because node-bound rewrite is deterministic-only.
- [ ] Add a message-level OpenAI-compatible generation method and implement the minimal node-bound rewrite flow.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Simulation hard gate

**Files:**
- Modify: `tests/evals/test_simulation.py`
- Modify: `evals/simulation.py`

- [ ] Add tests proving successful `route_role=node_binding` evidence passes while deterministic fallback still fails.
- [ ] Run the focused eval tests and confirm the new node-binding case fails.
- [ ] Extend only the accepted real-model role set to include `node_binding`.
- [ ] Run the focused eval tests and confirm they pass.

### Task 3: Regression and contract verification

**Files:**
- Modify if required by observed failures only: affected implementation/tests

- [ ] Run affected service, decision graph, eval, and API tests.
- [ ] Run the complete Python suite and contract suite.
- [ ] Run targeted secret and diff checks.

### Task 4: K3s-backed 30-turn evidence

**Files:**
- Create: ignored/local report output under the repository report directory selected by the existing simulation runner.

- [ ] Generate the local ACS runtime env from K3s without printing secret values and verify file mode `0600`.
- [ ] Start/verify PostgreSQL and MinIO forwards, the local ACS API, and the required Open ERP fixed-snapshot path.
- [ ] Execute the fixed 10-conversation/30-turn simulation with `source=simulation` and verify zero external sends.
- [ ] Review every reply for natural Chinese and fact safety; fix model/validator defects without weakening factual gates.

### Task 5: Publish for protected-main review

**Files:**
- Modify: `docs/development-handoff.md` only if implementation scope documentation changes.

- [ ] Re-run fresh completion verification and inspect the complete diff.
- [ ] Commit the scoped files, push `codex/acs-node-bound-grounded-rewrite`, and create a PR.
- [ ] Wait for required checks and report commit, PR, tests, report path, and before/after evidence without merging.
