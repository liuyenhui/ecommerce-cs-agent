# ACS Reply Generation Model Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route safe ACS candidate drafts through the organization’s released `reply_generation` model configuration, validate the model output against deterministic facts, and retain deterministic fallback behavior.

**Architecture:** Resolve the running organization-scoped scenario route from PostgreSQL, call the configured OpenAI-compatible primary/fallback Provider through the existing Secret/origin/TLS boundary, and let the model rewrite only an allowlisted deterministic draft. Reject factual or safety drift, record metadata-only metrics, and keep public APIs unchanged.

**Tech Stack:** Python 3.13, psycopg, LangGraph, stdlib HTTP/TLS adapters, Pydantic, pytest, K3s PostgreSQL/Secret runtime.

---

### Task 1: Resolve released reply-generation routes

**Files:**
- Create: `ecommerce_cs_agent/services/llm_runtime.py`
- Test: `tests/services/test_llm_runtime.py`

- [ ] **Step 1: Write route-resolution RED tests**

Test that only the organization’s `running` release and enabled `reply_generation` route are returned, including primary/fallback Provider fields and policy values. Add negative cases for no release, disabled route/provider, pending release, and cross-organization store scope.

```python
route = repository.resolve_reply_route(organization_id="org-a", store_id="store-a")
assert route.scenario == "reply_generation"
assert route.primary.model == "deepseek-chat"
assert route.fallback is not None
assert repository.resolve_reply_route(organization_id="org-b", store_id="store-a") is None
```

- [ ] **Step 2: Verify RED**

Run `/tmp/acs-simulation-eval-venv/bin/python -m pytest tests/services/test_llm_runtime.py -q`.
Expected: import failure because `llm_runtime` does not exist.

- [ ] **Step 3: Implement typed route objects and repositories**

Define immutable `RuntimeProvider`, `RuntimeRoutePolicy`, and `RuntimeReplyRoute` dataclasses plus `RuntimeRouteRepository`, null/in-memory implementations, and `PostgresRuntimeRouteRepository`. Query `llm_release_record`, `llm_config_version`, `llm_scenario_route`, and primary/fallback `llm_provider_config`; require the exact organization, `running` release, enabled `reply_generation` route, active Providers, and same-organization store.

- [ ] **Step 4: Verify GREEN and commit**

```bash
/tmp/acs-simulation-eval-venv/bin/python -m pytest tests/services/test_llm_runtime.py -q
git add ecommerce_cs_agent/services/llm_runtime.py tests/services/test_llm_runtime.py
git commit -m "feat: resolve released ACS model routes"
```

### Task 2: Add a secure Provider invocation client

**Files:**
- Modify: `ecommerce_cs_agent/services/llm_governance_adapters.py`
- Create: `ecommerce_cs_agent/services/llm_provider.py`
- Test: `tests/services/test_llm_provider.py`
- Modify: `tests/services/test_llm_governance_adapters.py`

- [ ] **Step 1: Write Provider-client RED tests**

Use injected Secret resolver and pinned transport to verify OpenAI-compatible request shape, strict JSON response parsing, token counts, HTTPS/origin binding, no redirects, bounded response, absolute timeout, retries, 401/429/5xx mapping, primary-to-fallback, and Secret/body redaction.

```python
result = client.generate(route.primary, messages=messages, policy=route.policy)
assert result.reply_payload == {"reply_text": "可以的，这款比熊可以用。"}
assert result.input_tokens == 42
assert "Authorization" not in result.safe_metadata
```

- [ ] **Step 2: Verify RED**

Run `tests/services/test_llm_provider.py`; expect missing client failures.

- [ ] **Step 3: Extract a reusable secure session boundary**

Refactor the current Kubernetes Secret/origin/pinned-IP logic into a reusable operation that resolves one allowlisted Secret, creates authorization headers in memory, executes one supplied request via `_PinnedProviderTransport`, and discards the Secret. Preserve all connection-test behavior.

- [ ] **Step 4: Implement chat completions**

POST `<base_url>/chat/completions` with the released model, messages, temperature, max tokens, and `response_format={"type":"json_object"}`. Parse only `choices[0].message.content`, usage counts, and safe metadata. Map failures to `auth_failed`, `rate_limited`, `provider_unavailable`, `timeout`, or `invalid_response`.

- [ ] **Step 5: Verify GREEN and commit**

```bash
/tmp/acs-simulation-eval-venv/bin/python -m pytest tests/services/test_llm_provider.py tests/services/test_llm_governance_adapters.py -q
git add ecommerce_cs_agent/services/llm_governance_adapters.py ecommerce_cs_agent/services/llm_provider.py tests/services/test_llm_provider.py tests/services/test_llm_governance_adapters.py
git commit -m "feat: invoke governed ACS model providers"
```

### Task 3: Build and validate grounded model rewrites

**Files:**
- Create: `ecommerce_cs_agent/services/reply_generation.py`
- Test: `tests/services/test_reply_generation.py`
- Modify: `ecommerce_cs_agent/services/grounded_reply.py`

- [ ] **Step 1: Write prompt and validator RED tests**

Require the prompt to contain only the current question, minimal history, deterministic draft, selected safe facts, and constraints. Reject unrelated entities, raw payload/source refs, full tracking IDs, PII, Secret-like values, added numbers/statuses/carriers, medical efficacy, arrival guarantees, prompt leakage, JSON dumps, and missing deterministic facts.

```python
validated = validate_model_reply(
    deterministic="从商品名称看，这款适合比熊使用。",
    model_reply="可以的，这款比熊可以用。皮肤敏感的话，建议先少量试用。",
    facts=grounded_facts,
)
assert "比熊可以用" in validated
```

- [ ] **Step 2: Verify RED**

Run `tests/services/test_reply_generation.py`; expect missing module failures.

- [ ] **Step 3: Implement prompt contract and validator**

Define `GroundedRewriteRequest`, `GroundedRewriteResult`, `build_rewrite_messages()`, and `validate_model_reply()`. Extend grounded outcomes with a safe fact manifest containing required facts, allowed numbers/entities, prohibited claims, and privacy constraints.

- [ ] **Step 4: Verify GREEN and commit**

```bash
/tmp/acs-simulation-eval-venv/bin/python -m pytest tests/services/test_reply_generation.py tests/services/test_grounded_reply.py -q
git add ecommerce_cs_agent/services/reply_generation.py ecommerce_cs_agent/services/grounded_reply.py tests/services/test_reply_generation.py tests/services/test_grounded_reply.py
git commit -m "feat: validate grounded model rewrites"
```

### Task 4: Integrate model generation, fallback, trace, and metrics

**Files:**
- Modify: `ecommerce_cs_agent/services/llm.py`
- Modify: `ecommerce_cs_agent/services/decision.py`
- Modify: `ecommerce_cs_agent/services/decision_graph.py`
- Modify: `ecommerce_cs_agent/services/repository.py`
- Test: `tests/services/test_decision_graph.py`
- Test: `tests/services/test_llm_runtime.py`

- [ ] **Step 1: Write decision-path RED tests**

Cover successful primary rewrite, primary-to-fallback, missing route, 401, timeout, fabricated output, unchanged handoff, simulation no-send, safe trace metadata, and one metadata-only metric per attempted route role.

```python
assert response["candidates"][0]["reply_text"] == "可以的，这款比熊可以用。"
assert response["trace"]["model"]["route_role"] == "primary"
assert "prompt" not in response["trace"]["model"]
```

- [ ] **Step 2: Verify RED**

Run the named decision tests and confirm the deterministic draft is still returned.

- [ ] **Step 3: Implement `GovernedReplyProvider`**

Resolve the route per organization/store, build safe messages, try primary then configured fallback, validate every output, and otherwise return the deterministic draft. Preserve action, handoff, evidence, entity IDs, and policy gates.

- [ ] **Step 4: Record metadata-only invocation metrics**

Insert `llm_invocation_metric` with route ID/role, organization/store, tokens, latency, status, safe error code, cost, and currency. The method must not accept Prompt or response fields.

- [ ] **Step 5: Verify GREEN and commit**

```bash
/tmp/acs-simulation-eval-venv/bin/python -m pytest tests/services/test_decision_graph.py tests/services/test_llm_runtime.py -q
git add ecommerce_cs_agent/services/llm.py ecommerce_cs_agent/services/decision.py ecommerce_cs_agent/services/decision_graph.py ecommerce_cs_agent/services/repository.py tests/services/test_decision_graph.py tests/services/test_llm_runtime.py
git commit -m "feat: generate ACS replies through released models"
```

### Task 5: Require model-backed evaluation evidence

**Files:**
- Modify: `evals/simulation.py`
- Modify: `evals/models.py`
- Modify: `tests/evals/test_simulation.py`
- Modify: `docs/development-handoff.md`

- [ ] **Step 1: Add RED tests**

Require every non-handoff model-backed turn to expose safe model version, route role, status, and fallback-used fields without Prompt/response/Secret. Deterministic fallback cannot be reported as a successful model call.

- [ ] **Step 2: Verify RED**

Run `tests/evals/test_simulation.py`; expect missing model-evidence failures.

- [ ] **Step 3: Extend reports and assertions**

Add safe model metadata to the question/reply report, keep natural-language/fact checks unchanged, exclude provider payloads from JSONL, and document runtime route/fallback behavior.

- [ ] **Step 4: Verify and commit**

```bash
/tmp/acs-simulation-eval-venv/bin/python -m pytest tests/evals/test_simulation.py tests/evals/test_runner_mock.py -q
git add evals/simulation.py evals/models.py tests/evals/test_simulation.py docs/development-handoff.md
git commit -m "test: require governed model reply evidence"
```

### Task 6: Full regression and real Provider acceptance

**Files:**
- Produce ignored reports under: `reports/evals/`

- [ ] **Step 1: Run affected, full, and contract suites**

```bash
/tmp/acs-simulation-eval-venv/bin/python -m pytest tests/services/test_llm_runtime.py tests/services/test_llm_provider.py tests/services/test_reply_generation.py tests/services/test_decision_graph.py tests/evals/test_simulation.py -q
/tmp/acs-simulation-eval-venv/bin/python -m pytest -q
/tmp/acs-simulation-eval-venv/bin/python -m pytest tests/contract -q
```

- [ ] **Step 2: Verify the current released Provider safely**

Use the ACS debug flow and inspect connection status without printing credentials. If it returns 401, verify Secret reference/key existence or hash only. Update K3s state only if an already-authorized valid credential is available; never invent or expose a key.

- [ ] **Step 3: Start K3s-backed ACS and Open ERP**

Start PostgreSQL/MinIO forwards, current worktree API, and Open ERP debug server. Require both health endpoints to return 200 and the released route to resolve for the test organization/store.

- [ ] **Step 4: Run unchanged 30-turn suite through the real model**

Acceptance requires 30/30, zero blocked/needs-review, successful model evidence on each safe candidate, no Provider-failure deterministic fallback, complete trace, and zero external sends.

- [ ] **Step 5: Human-review and final review**

Reject robotic repetition, JSON, irrelevant entities, factual drift, medical claims, arrival guarantees, or privacy leakage. Run Critical/Important review of route scoping, Secret handling, SSRF/TLS, validator, metric privacy, fallback, and reports. Fix findings with RED tests, rerun all gates, commit, and keep the protected branch/worktree without pushing main.
