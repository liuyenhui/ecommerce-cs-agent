# Decision Runtime and Requirements Test Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the existing LangGraph conditional-runtime work and map every first-version requirement to deterministic and live evidence.

**Architecture:** Keep the Agent API and decision graph as the source of runtime truth. Verify the already-present conditional edges, checkpoint identity, skipped-node trace model, and safe auto-reply behavior before adding a checked-in requirement-to-test matrix. Do not widen the API contract unless a stable field is actually missing.

**Tech Stack:** Python 3.13, FastAPI, LangGraph 1.2, pytest, OpenAPI YAML, Markdown validation, AntV X6 architecture validators.

---

### Task 1: Review and lock the existing conditional decision runtime

**Files:**
- Modify if needed: `ecommerce_cs_agent/services/decision_graph.py`
- Modify if needed: `ecommerce_cs_agent/services/decision.py`
- Test: `tests/services/test_decision_graph.py`
- Test: `tests/api/test_v1_api.py`

- [ ] **Step 1: Run the focused runtime tests against the existing working-tree changes**

Run:

```bash
PATH=.venv/bin:$PATH python -m pytest \
  tests/services/test_decision_graph.py \
  tests/api/test_v1_api.py -q
```

Expected: all focused tests pass. If a test fails, use `superpowers:systematic-debugging` before changing implementation.

- [ ] **Step 2: Add a failing assertion for the actual action branch node set**

Add to `test_decision_graph_action_request_and_trace_match_contract`:

```python
action_gate = next(node for node in graph["nodes"] if node["id"] == "action_gate")
generate_candidate = next(node for node in graph["nodes"] if node["id"] == "generate_candidate")
assert action_gate["status"] == "completed"
assert generate_candidate["status"] == "skipped"
assert any(edge["condition"] == "action_request" and edge["taken"] for edge in graph["edges"])
```

- [ ] **Step 3: Run the single test and verify the assertion is meaningful**

Run:

```bash
PATH=.venv/bin:$PATH python -m pytest \
  tests/services/test_decision_graph.py::test_decision_graph_action_request_and_trace_match_contract -q
```

Expected: PASS if the existing conditional edge implementation is correct; FAIL identifies the exact action-branch trace mismatch to fix.

- [ ] **Step 4: Keep the minimal runtime implementation that satisfies the branch contract**

The compiled graph in `ReplyDecisionGraph._build_stategraph()` must keep these conditional routes:

```python
graph.add_conditional_edges(
    "context_gate",
    _route_after_context_gate,
    {
        "context_request": "policy_gate",
        "handoff": "policy_gate",
        "context_complete": "action_gate",
    },
)
graph.add_conditional_edges(
    "action_gate",
    _route_after_action_gate,
    {
        "candidate": "generate_candidate",
        "action_request": "policy_gate",
    },
)
```

Do not reintroduce no-op execution of nodes that should be marked `skipped`.

- [ ] **Step 5: Re-run focused tests**

Run the command from Step 1.

Expected: PASS.

### Task 2: Complete safety, checkpoint, and simulation evidence

**Files:**
- Modify: `tests/services/test_decision_graph.py`
- Modify: `tests/api/test_v1_api.py`

- [ ] **Step 1: Strengthen the existing safe-auto-reply service test before changing runtime code**

Extend `test_decision_graph_uses_approved_knowledge_for_safe_auto_reply` with trace assertions:

```python
graph = response["trace"]["graph"]
assert any(edge["condition"] == "candidate" and edge["taken"] for edge in graph["edges"])
assert any(edge["condition"] == "persist" and edge["taken"] for edge in graph["edges"])
assert next(node for node in graph["nodes"] if node["id"] == "generate_candidate")["status"] == "completed"
assert response["auto_reply"]["approved_by_policy_gate"] is True
```

Use synthetic product knowledge and do not add live model calls.

- [ ] **Step 2: Run only the strengthened test**

Run:

```bash
PATH=.venv/bin:$PATH python -m pytest \
  tests/services/test_decision_graph.py::test_decision_graph_uses_approved_knowledge_for_safe_auto_reply -q
```

Expected: PASS when the existing conditional candidate branch and policy gate are correctly represented. If it fails, fix only the mismatched branch or trace status.

- [ ] **Step 3: Add a failing resumed-checkpoint API assertion**

Extend the context-refill API test with:

```python
completed = second_refill.json()["decision"]
assert completed["trace"]["resumed_from_checkpoint"] is True
assert completed["trace"]["langgraph_checkpoint_id"]
assert completed["trace"]["thread_id"] == decision["decision_id"]
```

- [ ] **Step 4: Run the context-refill test**

Run:

```bash
PATH=.venv/bin:$PATH python -m pytest tests/api/test_v1_api.py -k context_refill -q
```

Expected: PASS after the response exposes the persisted decision trace; if the API response shape differs, assert through the existing returned object rather than adding a duplicate endpoint.

- [ ] **Step 5: Verify simulation never sends externally**

Run:

```bash
PATH=.venv/bin:$PATH python -m pytest \
  tests/api/test_v1_api.py::test_customer_admin_simulation_creates_trace_without_external_send -q
```

Expected: PASS with `external_send == {"attempted": False, "reason": "simulation_only"}`.

### Task 3: Create the requirements-to-test matrix

**Files:**
- Create: `docs/requirements-test-matrix.md`
- Modify: `docs/testing.md`
- Modify: `docs/development-handoff.md`
- Test: `tests/contract/test_markdown_links.py`

- [ ] **Step 1: Write the matrix header and required columns**

Create `docs/requirements-test-matrix.md` with this table structure:

```markdown
# 第一版需求测试矩阵

| ID | 需求来源 | 正向案例 | 拒绝/异常案例 | 自动化证据 | 线上证据 | 当前状态 |
| --- | --- | --- | --- | --- | --- | --- |
| RQ-01 | Development Readiness: 外部接入 | 合法 API token 创建决策 | 缺少 token 返回 401 | `tests/api/test_v1_api.py::test_reply_decision_requires_external_bearer_token` | API smoke | 已覆盖 |
```

Add one row for every item in `docs/development-readiness.md` section “第一版必须实现”: external access, decision outputs, typed refill, action loop, human feedback, orchestration, persistence, stateless k8s, Customer Admin, System Admin, rule gate, and test gate.

- [ ] **Step 2: Link the matrix from testing documentation**

Add this sentence near the top of `docs/testing.md`:

```markdown
第一版需求、正反向案例、自动化证据与线上验收状态统一维护在 [Requirements Test Matrix](requirements-test-matrix.md)。
```

- [ ] **Step 3: Add the dated handoff entry**

Under `2026-07-10` in `docs/development-handoff.md`, add one bullet stating that `docs/requirements-test-matrix.md` is now the test-case coverage source.

- [ ] **Step 4: Validate links and matrix completeness**

Run:

```bash
PATH=.venv/bin:$PATH python -m pytest tests/contract/test_markdown_links.py -q
python scripts/check_markdown_links.py .
rg -n '^\| RQ-' docs/requirements-test-matrix.md
```

Expected: link checks pass and at least 12 `RQ-` rows are printed.

### Task 4: Validate and commit the runtime/test-matrix slice

**Files:**
- Existing changed runtime, tests, architecture docs, and new matrix files from Tasks 1–3.

- [ ] **Step 1: Run the runtime and architecture validation set**

```bash
PATH=.venv/bin:$PATH python -m pytest tests/services/test_decision_graph.py tests/api/test_v1_api.py -q
node docs/scripts/validate-x6-architecture-runtime.mjs
node docs/scripts/validate-business-flow-x6-labels.mjs
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Stage only this slice and scan it for sensitive patterns**

```bash
git add \
  ecommerce_cs_agent/services/decision.py \
  ecommerce_cs_agent/services/decision_graph.py \
  tests/services/test_decision_graph.py \
  tests/api/test_v1_api.py \
  docs/system-architecture.html \
  docs/requirements-test-matrix.md \
  docs/testing.md \
  docs/development-handoff.md
git diff --cached --check
git diff --cached | rg -n 'sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET' || true
```

Expected: no sensitive value match.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: complete conditional AI decision workflow"
```
