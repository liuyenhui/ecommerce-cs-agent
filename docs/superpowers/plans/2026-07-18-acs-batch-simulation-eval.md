# ACS Batch Simulation Eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing eval path with deterministic, privacy-safe, snapshot-backed multi-turn ACS simulations without creating a second decision path.

**Architecture:** Add a fixture schema and adapter that converts each turn into the existing `TestCase`/`LiveAgentClient` flow. The adapter carries one conversation history across turns, refills only requested typed contexts, and adds simulation-specific hard assertions and JSONL/summary evidence.

**Tech Stack:** Python 3.11+, Pydantic 2, httpx, pytest, existing eval runner and public ACS APIs.

---

### Task 1: Pin fixture and privacy contracts

**Files:**
- Create: `evals/simulation.py`
- Create: `tests/evals/test_simulation.py`

- [ ] Write failing tests for snapshot hash validation, 10 conversations / 3-5 turns / at least 30 turns, generation-model metadata, and forbidden buyer PII.
- [ ] Run the focused tests and confirm failure.
- [ ] Implement the minimal strict Pydantic fixture schema and recursive privacy validator.
- [ ] Run the focused tests and confirm success.

### Task 2: Reuse the public decision and typed-refill path

**Files:**
- Modify: `evals/simulation.py`
- Modify: `evals/runner.py`
- Test: `tests/evals/test_simulation.py`

- [ ] Write failing tests proving every turn uses `source=simulation`, carries prior buyer/assistant messages, and refills only `products`, `orders`, and `logistics` through the existing endpoints.
- [ ] Implement a conversation runner that adapts turns to existing `TestCase` objects and `LiveAgentClient` methods.
- [ ] Preserve the final refill response for assertions and append its safe assistant output to the next turn history.
- [ ] Run the focused tests.

### Task 3: Add simulation hard gates and reports

**Files:**
- Modify: `evals/simulation.py`
- Modify: `evals/assertions.py`
- Modify: `evals/models.py`
- Modify: `evals/cli.py`
- Test: `tests/evals/test_simulation.py`

- [ ] Write failing tests for factual allowlists, coreference entity checks, context request checks, handoff policy, complete LangGraph trace, `external_send.attempted=false`, and zero blocked/needs-review.
- [ ] Implement deterministic assertions whose expected facts are validated against the snapshot before execution.
- [ ] Write one JSONL row per turn plus a summary JSON containing fixture/model/hash and aggregate gates.
- [ ] Add a CLI entry that exits nonzero unless every turn passes with zero blocked and zero needs-review.

### Task 4: Baseline, regression, and real-path acceptance

**Files:**
- Create at runtime only: `reports/evals/<run-id>.jsonl`
- Create at runtime only: `reports/evals/<run-id>-summary.json`

- [ ] Preserve a pre-change baseline result or explicit environment-blocker record.
- [ ] Run focused and complete eval tests.
- [ ] Run the fixed 10-conversation fixture against the local/K3s-backed ACS path when the snapshot fixture and credentials arrive.
- [ ] Record real failures, targeted fixes, before/after report paths, or precise service/credential blockers.
- [ ] Run the targeted secret scan, exclude `package-lock.json`, and commit only scoped files.
