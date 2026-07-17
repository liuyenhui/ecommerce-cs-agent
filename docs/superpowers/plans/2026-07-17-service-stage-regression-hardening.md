# ACS Service-Stage Regression Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the 30 Dev ACS simulation decisions into a repeatable regression suite, fix the observed service-stage gaps, and keep generating nearby phrasings until both offline and Dev live decisions match the reviewed expectations without any simulation auto-send.

**Architecture:** Keep the existing hybrid classifier boundary: deterministic rules provide the safety baseline, the OpenAI-compatible provider may enrich an unknown result, and LangGraph persists the normalized classification and classifier diagnostics. Harden semantic rule groups rather than special-casing whole sentences, add a reviewed simulation corpus with primary/secondary stage and action expectations, and reuse the public simulation endpoint for sequential Dev verification.

**Tech Stack:** Python 3.13, pytest, FastAPI/TestClient, LangGraph decision service, PostgreSQL trace verification, Admin Web existing trace UI, GitHub Actions image publishing, Helm/GitOps Dev deployment.

---

### Task 1: Freeze the 30-message baseline and nearby paraphrase expectations

**Files:**
- Create: `tests/fixtures/service_stage_simulation_regression.json`
- Modify: `tests/services/test_service_stage.py`
- Modify: `tests/services/test_decision_graph.py`

**Step 1: Write the failing corpus test**

Add the 30 reviewed messages with expected `primary_stage`, `secondary_stages`, `reason_code`, `needs_context`, and simulation `expected_action`. Add nearby phrasings for each observed gap: inventory/dispatch, unfulfilled-order note, delivered device failure, delivered safety complaint, repurchase upgrade, and mixed current intents.

**Step 2: Run the focused tests and confirm RED**

Run: `/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/pytest -q tests/services/test_service_stage.py tests/services/test_decision_graph.py -k 'simulation_regression or nearby'`

Expected: failures for the observed eight stage/secondary-stage gaps.

**Step 3: Add decision-level simulation assertions**

Assert the service stage in the public decision response, the expected decision action, `source=simulation`, and that `auto_reply` is always null even when product knowledge is available.

### Task 2: Fix deterministic stage semantics with minimal term-level rules

**Files:**
- Modify: `ecommerce_cs_agent/services/service_stage.py`
- Modify: `tests/services/test_service_stage.py`

**Step 1: Add focused failing unit tests**

Cover `现货/什么时候能发`, `这单/未出库/派送`, `无法开机`, `异味/发烫/投诉`, `复购升级版`, `运输中 + 再买`, `退掉 + 再买`, and `保修坏了 + 新款多少钱`.

**Step 2: Run and record RED**

Run: `/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/pytest -q tests/services/test_service_stage.py`

**Step 3: Implement minimal semantic groups**

Extend product availability/price/version intent, fulfillment/order-reference intent, delivered quality/safety/complaint intent, repurchase intent, return wording, and mixed-intent detection. Preserve the signed-delivery boundary, per-message classification, old-customer repurchase rule, and unknown behavior for genuinely ambiguous text.

**Step 4: Run and confirm GREEN**

Run: `/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/pytest -q tests/services/test_service_stage.py`

### Task 3: Harden provider normalization and classifier diagnostics

**Files:**
- Modify: `tests/services/test_reply_llm.py`
- Modify: `ecommerce_cs_agent/services/llm.py` only if a failing provider contract test proves a gap
- Modify: `tests/services/test_decision_graph.py`

**Step 1: Add provider contract tests**

Verify valid model JSON cannot override a known deterministic primary stage, valid secondary stages are merged with deterministic secondary stages, invalid/timeout output falls back to the hardened baseline, and classifier source/error codes remain visible in trace.

**Step 2: Run focused tests and confirm any provider RED**

Run: `/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/pytest -q tests/services/test_reply_llm.py tests/services/test_decision_graph.py -k 'service_stage or classifier'`

**Step 3: Make only evidence-backed provider changes**

If the tests show model normalization can discard a deterministic secondary stage, union the baseline and model secondary stages and recompute `mixed_intent`. Do not let model output bypass deterministic stage, context, risk, or simulation gates.

### Task 4: Validate the complete offline decision corpus

**Files:**
- Modify: `tests/fixtures/service_stage_simulation_regression.json`
- Modify: `tests/services/test_service_stage.py`
- Modify: `tests/services/test_decision_graph.py`

**Step 1: Add a second nearby-question round**

Generate at least two meaning-preserving paraphrases per observed failure family, using different wording rather than copying the original sentence. Keep reviewed expectations explicit in the fixture.

**Step 2: Run corpus and decision integration tests**

Run: `/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/pytest -q tests/services/test_service_stage.py tests/services/test_reply_llm.py tests/services/test_decision_graph.py`

Expected: all original 64 cases, all 30 simulation cases, and every nearby variant pass.

**Step 3: Run the full Python suite**

Run: `/Users/huiliu/Documents/software/ecommerce-cs-agent/.venv/bin/pytest -q`

Expected: no regression from the 623-pass baseline.

### Task 5: Synchronize implementation handoff and test evidence

**Files:**
- Modify: `docs/development-handoff.md`
- Modify: `docs/development-readiness.md` if its test matrix enumerates service-stage cases

**Step 1: Add the dated change entry**

Document the production failure mechanism, new reviewed corpus, deterministic fallback hardening, provider secondary-stage preservation, and Dev live acceptance criteria. Do not add customer text, model prompts, or secrets to trace documentation.

**Step 2: Run documentation and secret checks**

Run: `git diff --check`

Run: `rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET" docs tests ecommerce_cs_agent`

Expected: no introduced secret value; key names in existing documentation must remain placeholders only.

### Task 6: Review, publish, deploy, and iterate against Dev ACS

**Files:**
- Review: `.github/workflows/publish-images.yml`
- Review: Helm/GitOps deployment configuration in the existing deployment repository

**Step 1: Verify branch diff and commit intentionally**

Run targeted tests, the full suite, `git diff --check`, and a staged secret scan. Review the diff for sentence-specific hacks and unrelated changes.

**Step 2: Push and open a PR**

Push `codex/service-stage-regression-hardening`, open a ready PR, and monitor all required checks. Automatically fix actionable review or CI failures in scope.

**Step 3: Merge and publish through GitHub Actions**

After required checks pass, merge normally, run the repository image-publish workflow for the Dev tag, and verify both API and Admin images are pullable. Do not push images from the Codex workstation.

**Step 4: Deploy through the existing GitOps path**

Update the Dev image tag using the established GitOps workflow, wait for API/Admin rollout completion, and verify live health before functional testing.

**Step 5: Run sequential live simulation rounds**

Submit the 30 base messages with new request IDs and `source=simulation`, one at a time to avoid provider throttling. Verify primary/secondary stage, action, classifier source/error code, trace node, and `auto_reply = null`. Then submit the nearby-question corpus with fresh IDs.

**Step 6: Repeat until accepted**

For every mismatch, capture only the synthetic message ID and redacted classifier summary, add a failing local test, make the smallest semantic fix, rerun all offline tests, republish/redeploy, and retest only fresh near variants plus the full base set. Completion requires 100% reviewed stage/action expectations and zero simulation auto-send.
