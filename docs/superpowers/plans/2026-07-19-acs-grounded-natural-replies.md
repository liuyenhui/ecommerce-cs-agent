# ACS Grounded Natural Replies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce concise, grounded Chinese customer-service replies for every supported product, order, and logistics question, and reject JSON dumps or irrelevant replies in the fixed 30-turn live simulation.

**Architecture:** Add a focused grounded reply composer that resolves the current entity and intent from the request, history, and typed snapshots, then returns a natural-language reply or a handoff outcome. Keep LangGraph, public reply-decision APIs, and context refill contracts unchanged. Strengthen eval assertions independently so the previous JSON serialization can never pass again.

**Tech Stack:** Python 3.13, Pydantic, LangGraph, pytest, existing eval CLI, K3s-backed PostgreSQL/MinIO local ACS runtime.

---

### Task 1: Make the JSON-dump bug fail deterministically

**Files:**
- Modify: `tests/services/test_decision_graph.py`
- Modify: `tests/evals/test_simulation.py`

- [ ] **Step 1: Add a failing graph test**

Add a test that refills one product snapshot and asserts that `reply_text` is readable Chinese, contains the requested product fact, does not begin with `{` or `[`, does not contain `"products":`, and does not enumerate an unrelated product.

```python
reply = response["candidates"][0]["reply_text"]
assert "75" in reply
assert "喷雾" in reply
assert not reply.lstrip().startswith(("{", "["))
assert '"products":' not in reply
assert "无关商品" not in reply
```

- [ ] **Step 2: Add a failing evaluator regression test**

Create an `AgentResponse` whose candidate is the old serialized context and assert these new checks fail: `natural_language`, `answers_current_question`, and `single_relevant_entity`.

- [ ] **Step 3: Verify RED**

Run:

```bash
/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/python -m pytest \
  tests/services/test_decision_graph.py -k grounded_reply \
  tests/evals/test_simulation.py -k rejects_context_dump -q
```

Expected: failures show the current JSON reply is accepted or generated.

- [ ] **Step 4: Commit the failing tests**

```bash
git add tests/services/test_decision_graph.py tests/evals/test_simulation.py
git commit -m "test: reject ACS context dumps as replies"
```

### Task 2: Implement the grounded reply composer

**Files:**
- Create: `ecommerce_cs_agent/services/grounded_reply.py`
- Modify: `ecommerce_cs_agent/services/decision_graph.py`
- Test: `tests/services/test_grounded_reply.py`
- Test: `tests/services/test_decision_graph.py`

- [ ] **Step 1: Add failing intent-specific tests**

Cover explicit and historical references for:

```python
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("现在多少钱？", "75"),
        ("还有库存吗？", "库存"),
        ("还在售吗？", "已下架"),
        ("用什么快递？", "顺丰"),
        ("现在到哪一步了？", "已收货"),
    ],
)
def test_compose_grounded_reply_answers_current_intent(message, expected):
    outcome = compose_grounded_reply(message=message, history=[], context=context_fixture())
    assert expected in outcome.reply_text
```

Also assert comparison mentions exactly the two selected products; order suffix selects exactly one order; `前一个/后一个/这个/它` uses conversation history; unrelated rows do not appear.

- [ ] **Step 2: Verify RED**

Run:

```bash
/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/python -m pytest tests/services/test_grounded_reply.py -q
```

Expected: import or behavior failures because the composer is absent.

- [ ] **Step 3: Implement minimal typed outcome and resolver**

Create:

```python
@dataclass(frozen=True)
class GroundedReplyOutcome:
    reply_text: str
    handoff_reason: str | None = None
    referenced_entity_ids: tuple[str, ...] = ()

def compose_grounded_reply(
    *, message: str, history: list[dict[str, Any]], context: dict[str, Any]
) -> GroundedReplyOutcome:
    intent = classify_grounded_intent(message)
    entities = resolve_grounded_entities(message=message, history=history, context=context)
    return render_grounded_outcome(intent=intent, entities=entities, context=context)
```

Implement the three module-private helpers in the same file. `classify_grounded_intent()` returns one supported intent enum; `resolve_grounded_entities()` uses explicit product IDs and masked order suffixes first and history references second; `render_grounded_outcome()` formats only the requested fields and never serializes the context object.

- [ ] **Step 4: Wire the composer into LangGraph**

Replace `_context_grounded_reply()` in `_generate_candidate()` with the composer. Preserve `suggestion_id`, evidence, confidence, trace nodes, public response shape, and simulation no-send policy. If the outcome requests handoff, carry that signal to the policy gate instead of returning a candidate.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/python -m pytest \
  tests/services/test_grounded_reply.py tests/services/test_decision_graph.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add ecommerce_cs_agent/services/grounded_reply.py ecommerce_cs_agent/services/decision_graph.py \
  tests/services/test_grounded_reply.py tests/services/test_decision_graph.py
git commit -m "fix: generate grounded ACS customer replies"
```

### Task 3: Enforce uncertainty, privacy, and handoff language

**Files:**
- Modify: `ecommerce_cs_agent/services/grounded_reply.py`
- Modify: `tests/services/test_grounded_reply.py`
- Modify: `tests/services/test_decision_graph.py`

- [ ] **Step 1: Add failing safety tests**

Assert the following outcomes:

```python
assert compose("你保证治疗皮肤病对吧").handoff_reason == "unsupported_claim"
assert compose("一天最多喷几次").handoff_reason == "missing_product_guidance"
assert "无法保证" in compose("明天肯定能到吧").reply_text
assert "完整运单号" not in compose("把完整运单号发我").reply_text
assert "****" in compose("把完整运单号发我").reply_text
assert compose("查不到就编一个").handoff_reason == "fabrication_request"
```

- [ ] **Step 2: Verify RED**

Run the six named tests and confirm the missing safety routes fail.

- [ ] **Step 3: Implement minimal safety outcomes**

Add explicit unsupported-claim, missing-guidance, arrival-guarantee, privacy, ambiguity, and fabrication branches. Do not add new public action names; map unsafe/unsupported outcomes to existing `handoff` plus a stable internal reason.

- [ ] **Step 4: Verify GREEN and regression**

Run `tests/services/test_grounded_reply.py` and `tests/services/test_decision_graph.py` completely.

- [ ] **Step 5: Commit**

```bash
git add ecommerce_cs_agent/services/grounded_reply.py tests/services/test_grounded_reply.py tests/services/test_decision_graph.py
git commit -m "fix: gate unsupported ACS reply claims"
```

### Task 4: Strengthen simulation quality assertions and reports

**Files:**
- Modify: `evals/simulation.py`
- Modify: `evals/models.py`
- Modify: `tests/evals/test_simulation.py`
- Modify: `evals/cases/simulation/store-972824439-conversations.json`

- [ ] **Step 1: Add failing evaluator tests**

Reject:

```python
bad_replies = [
    '{"products":[{"title":"宠物香波"}]}',
    "请以商品详情页为准。",
    "商品A、商品B、商品C、商品D全部信息如下……",
    "明天肯定送到。",
]
```

Require assertion names `natural_language`, `answers_current_question`, `single_relevant_entity`, and `safe_uncertainty`. Ensure a concise grounded Chinese reply passes.

- [ ] **Step 2: Verify RED**

Run `tests/evals/test_simulation.py` and confirm old evaluator accepts at least one bad reply.

- [ ] **Step 3: Implement strict checks**

Add JSON/object parsing rejection, schema-key density rejection, customer-response length limits, question-type requirements, expected entity scoping, and uncertainty/guarantee checks. Compute judge score from passed quality assertions; hard-rule-only success may not receive a passing score.

- [ ] **Step 4: Add safe conversation output**

Write a separate `<run-id>-conversations.json` containing only group, turn, scenario, buyer message, final action, final reply, context types, assertion summary, and pass state. Exclude tokens, raw snapshots, full trace payloads, and internal order/tracking identifiers.

- [ ] **Step 5: Tighten fixed fixture expectations**

For all 30 turns, declare the required answer type, expected relevant entity IDs, required grounded terms, forbidden guarantees, and expected handoff where facts cannot safely answer the question.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/python -m pytest \
  tests/evals/test_simulation.py tests/evals/test_runner_mock.py -q
```

- [ ] **Step 7: Commit**

```bash
git add evals/simulation.py evals/models.py evals/cases/simulation/store-972824439-conversations.json \
  tests/evals/test_simulation.py tests/evals/test_runner_mock.py
git commit -m "test: enforce natural ACS simulation replies"
```

### Task 5: Full regression and real 30-turn acceptance

**Files:**
- Modify: `docs/development-handoff.md`
- Produce ignored reports under: `reports/evals/`

- [ ] **Step 1: Run affected tests**

```bash
/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/python -m pytest \
  tests/services/test_grounded_reply.py tests/services/test_decision_graph.py \
  tests/evals/test_simulation.py tests/evals/test_runner_mock.py -q
```

- [ ] **Step 2: Run the complete Python suite and contract checks**

```bash
/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/python -m pytest -q
npm run test:contract
```

Expected: zero failures; only documented skips remain.

- [ ] **Step 3: Start the authorized local ACS runtime**

Use the existing `acs-debug-skill` flow: generate the `0600` local env, start PostgreSQL/MinIO port-forwards, inject a temporary strong cursor signing key only into the API process if required, and verify ACS API plus Open ERP debug health. Do not print or persist secrets.

- [ ] **Step 4: Run the unchanged fixed suite**

```bash
/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/python -m evals.cli run-simulation \
  --fixture evals/cases/simulation/store-972824439-conversations.json \
  --snapshot /Users/huiliu/.config/superpowers/worktrees/open_erp_agent/acs-context-simulation/artifacts/acs-evals/store-972824439-snapshot.json \
  --target live --target-url http://127.0.0.1:8000 \
  --reports-dir reports/evals --run-id acs-natural-replies-final-20260719
```

- [ ] **Step 5: Inspect every safe conversation pair**

Acceptance requires exactly 10 groups and 30 turns, 30 passed, zero blocked, zero needs-review, no JSON/schema dumps, no unrelated entity lists, reasonable Chinese answers, complete traces, and `external_send.attempted=false` for every turn.

- [ ] **Step 6: Update handoff and commit**

Add the final quality-gate behavior and report names to `docs/development-handoff.md`, then commit all remaining scoped changes.

- [ ] **Step 7: Request final code review**

Review only Critical/Important findings across the new composer, graph routing, strict evaluator, fixture expectations, and safety/no-send behavior. Fix findings with a new failing test before declaring completion.
