# ACS Natural Customer Service Tone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the existing 30-message fact/safety baseline while adding 20 fixed, human-approved tone cases and making one real `deepseek-v4-pro` node-binding run pass all 50 messages with grounded, concise, natural customer-service replies.

**Architecture:** Extend the simulation fixture schema with explicit fixture provenance, per-case style assertions, and human-review fields; keep all fact/entity/action/privacy/model-evidence assertions mandatory and evaluate style as an additional non-compensating gate. Improve only the deterministic intent/entity drafts and the grounded rewrite instruction needed for the fixed cases, leaving `validate_model_reply()` unchanged so every model rewrite remains bounded by the existing fact manifest.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, LangGraph reply decisions, OpenAI-compatible `deepseek-v4-pro`, K3s-backed PostgreSQL/MinIO simulation fixtures.

---

## File map

- `evals/cases/simulation/store-972824439-conversations.json`: retain the original 30 turns byte-for-byte in their existing groups; append the 20 approved tone cases, provenance, assertions, and human-review metadata.
- `evals/simulation.py`: validate 30+20 fixture structure and provenance, run style assertions, classify failures, and write safe review/summary evidence.
- `ecommerce_cs_agent/services/grounded_reply.py`: minimally recognize the approved colloquial, switching, urgency, medical-boundary, and privacy intents while preserving fact manifests.
- `ecommerce_cs_agent/services/reply_generation.py`: strengthen the grounded rewrite instruction for natural 1–2 sentence ecommerce support language; do not change `validate_model_reply()`.
- `ecommerce_cs_agent/services/llm.py`: preserve node-binding retry/metadata behavior and provide stricter retry guidance where style output fails safe validation.
- `tests/evals/test_simulation.py`, `tests/services/test_grounded_reply.py`, `tests/services/test_reply_llm.py`: TDD coverage for fixture, style gates, prompt contract, and grounded drafts.
- `reports/evals/acs-natural-customer-service-tone-*-summary.json`, `reports/evals/acs-natural-customer-service-tone-*-conversations.json`: fixed baseline/final evidence and human review.
- `docs/development-handoff.md`: dated implementation and report pointer.

### Task 1: Lock the 50-case fixture and provenance contract

**Files:**
- Modify: `tests/evals/test_simulation.py`
- Modify: `evals/simulation.py`
- Modify: `evals/cases/simulation/store-972824439-conversations.json`

- [ ] **Step 1: Write failing fixture tests**

Add tests that load the real fixture and assert: original IDs remain exactly the known 30 IDs; `tone-01` through `tone-20` exist exactly once; total turns equal 50; the 20 tone cases have `approved=true`, a non-empty `approved_at`, explicit `coverage`, non-empty `style_assertions`, and the snapshot hash remains `9128f2ef13710e6b826e271f`. Add negative model-validation tests for an unapproved tone case, missing generation timestamp/model, and missing style assertions.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/evals/test_simulation.py -q`

Expected: FAIL because the fixture schema only accepts 3–5 turn groups and the fixed fixture contains only the original 30 turns.

- [ ] **Step 3: Implement the minimal schema and fixture**

Add typed fields such as `coverage`, `style_assertions`, and `human_review` to `SimulationTurn`; allow the existing multi-turn groups plus approved one-turn tone groups; enforce exactly 30 non-tone and 20 approved `tone-*` turns for the real fixed suite while keeping `allow_partial` unit fixtures supported. Append the 20 specification-locked buyer messages, minimal redacted histories represented as prior turns or explicit safe setup history, exact expected terms/entities/boundaries, generation model, generated time, review time, and snapshot hash. Do not edit the original 30 turn objects.

- [ ] **Step 4: Run GREEN and inspect the fixture diff**

Run: `.venv/bin/python -m pytest tests/evals/test_simulation.py -q`

Run: `git diff --word-diff=porcelain -- evals/cases/simulation/store-972824439-conversations.json`

Expected: tests PASS and the diff shows only metadata plus appended tone cases, with no original 30 message/expectation changes.

### Task 2: Add explainable non-compensating style assertions and safe reports

**Files:**
- Modify: `tests/evals/test_simulation.py`
- Modify: `evals/simulation.py`

- [ ] **Step 1: Write failing style/report tests**

Parameterize customer replies that fail each named rule: `style.sentence_count_1_to_2`, `style.direct_answer_first`, `style.no_unnecessary_repetition`, `style.natural_customer_service_chinese`, `style.no_excessive_cuteness`, `style.calm_under_pressure`, `style.boundary_with_next_step`, and `style.concise_entity_reference`. Add forbidden-template cases for AI identity, system narration, empty reassurance, irrelevant greeting/cuteness, and content-free disclaimers. Assert every result records an assertion ID, boolean status, short safe evidence, primary failure category, source, external-send state, model evidence, and human-review status; assert summary contains assertion distributions, sentence counts, forbidden-template counts, external-send total, and model distribution.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/evals/test_simulation.py -q`

Expected: FAIL because style assertion IDs and report distributions do not exist.

- [ ] **Step 3: Implement minimal structural/semantic checks**

Add small deterministic helpers for Chinese sentence counting, direct-first detection, repetition/entity relevance, banned-template matching, calm-pressure language, and boundary-plus-next-step. Return short snippets only for banned-pattern evidence; never copy prompts, histories, raw HTTP bodies, or secrets. Run these checks only when declared by a tone case, append them after existing hard checks, and preserve failure semantics so style cannot compensate for a hard failure. Assign the first failed assertion to one of the specification categories and retain secondary assertion IDs.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/evals/test_simulation.py -q`

Expected: PASS with explicit style IDs and safe report fields.

### Task 3: Improve grounded drafts for the approved language phenomena

**Files:**
- Modify: `tests/services/test_grounded_reply.py`
- Modify: `ecommerce_cs_agent/services/grounded_reply.py`

- [ ] **Step 1: Write one failing test per behavior cluster**

Add focused tests for colloquial availability (`还能拍不`), urgent shipment/carrier wording, `今天能到吗` uncertainty, post-order product selection by a named product, prior-product switching (`还是刚才那瓶喷雾`), medical efficacy (`能治吗`), ingestion uncertainty (`舔到一点`), missing usage frequency (`多喷几次`), and masked tracking requests. Each test must assert exact grounded terms and referenced entity IDs, plus absence of unsupported facts or promises.

- [ ] **Step 2: Run RED and confirm failures are behavioral**

Run: `.venv/bin/python -m pytest tests/services/test_grounded_reply.py -q`

Expected: FAIL only on unrecognized intent/entity/boundary behavior, not fixture or import errors.

- [ ] **Step 3: Implement the minimum deterministic changes**

Extend `GroundedIntent` and phrase matching only as needed; resolve explicit named products before pronouns, let a named product disambiguate order items, and emit concise deterministic drafts containing every required fact term. Keep `_fact_manifest()` ownership of required terms, numbers, entities, and prohibited claims unchanged.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/services/test_grounded_reply.py -q`

Expected: PASS with no weakening of existing cases.

### Task 4: Strengthen natural-tone rewrite prompting without relaxing validation

**Files:**
- Modify: `tests/services/test_reply_llm.py`
- Modify: `ecommerce_cs_agent/services/reply_generation.py`
- Modify: `ecommerce_cs_agent/services/llm.py` only if retry guidance must distinguish a safe rejected rewrite

- [ ] **Step 1: Write failing prompt and validator-preservation tests**

Assert safe messages instruct the model to answer the current question first, use natural ecommerce support Chinese in 1–2 sentences, avoid question repetition/AI narration/empty reassurance/excessive cuteness, and retain all exact required facts. Retain and extend unsafe-output tests proving added numbers, changed statuses/entities, promises, identifiers, and privacy/prompt leakage are rejected.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/services/test_reply_llm.py -q`

Expected: FAIL on the new tone-instruction assertions while all validator safety tests continue to pass.

- [ ] **Step 3: Implement the minimum prompt change**

Update only `build_rewrite_messages()` system guidance (and stricter retry wording if needed). Do not change `validate_model_reply()` acceptance rules, allowed-number logic, entity/status checks, privacy checks, or fallback metadata.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/services/test_reply_llm.py tests/services/test_reply_generation.py -q`

Expected: PASS; validator tests demonstrate unchanged fact/safety strictness.

### Task 5: Run affected and repository test gates

**Files:**
- No production changes unless a genuine test-exposed defect is found.

- [ ] **Step 1: Run affected tests together**

Run: `.venv/bin/python -m pytest tests/services/test_grounded_reply.py tests/services/test_reply_llm.py tests/services/test_reply_generation.py tests/evals/test_simulation.py -q`

- [ ] **Step 2: Run the full suite**

Run: `.venv/bin/python -m pytest -q`

- [ ] **Step 3: Run contract tests**

Run: `.venv/bin/python -m pytest tests/contract -q`

Expected for every command: exit 0 and zero failures. If a failure reveals a real source/fixture defect, add a focused failing test, fix the real issue, and rerun all three commands; never weaken a gate.

### Task 6: Produce the real K3s-backed baseline and final 50-case evidence

**Files:**
- Create: `reports/evals/acs-natural-customer-service-tone-baseline-<run-id>.jsonl`
- Create: `reports/evals/acs-natural-customer-service-tone-baseline-<run-id>-summary.json`
- Create: `reports/evals/acs-natural-customer-service-tone-baseline-<run-id>-conversations.json`
- Create: `reports/evals/acs-natural-customer-service-tone-final-<run-id>.jsonl`
- Create: `reports/evals/acs-natural-customer-service-tone-final-<run-id>-summary.json`
- Create: `reports/evals/acs-natural-customer-service-tone-final-<run-id>-conversations.json`
- Create: `reports/evals/acs-natural-customer-service-tone-comparison.md`

- [ ] **Step 1: Prepare the approved local ACS environment**

Run the repository `dev:acs:env` and `dev:acs:port-forward` workflows from this worktree, confirm `.local/acs-runtime.env` mode is `0600`, then start the local API with the K3s-backed dev PostgreSQL/MinIO and online node-binding configuration. Verify `/health` without printing environment values or headers.

- [ ] **Step 2: Capture a safe baseline comparison**

Use a temporary detached worktree at implementation parent `22e13e2` (never main) or a compatibility runner that loads the new fixed fixture without changing production code. Run the fixed 20 tone cases through the real configured `deepseek-v4-pro` / `node_binding` path and save safe metadata-only baseline rows. Do not emit prompt text or raw model responses beyond the customer-visible final reply.

- [ ] **Step 3: Run the complete final 50**

Run: `.venv/bin/python -m evals.cli run-simulation --fixture evals/cases/simulation/store-972824439-conversations.json --snapshot <fixed-redacted-snapshot> --target live --target-url http://127.0.0.1:8000 --timeout 30 --run-id <new-fixed-run-id>`

Expected: `total=50 passed=50 blocked=0 needs_review=0`; all requests have `source=simulation`, all external-send attempts are false, all candidate rows show `deepseek-v4-pro`, `route_role=node_binding`, `status=succeeded`, `fallback_used=false`, and `validation_status=passed`.

- [ ] **Step 4: Audit privacy, facts, and every reply manually**

Programmatically assert external-send total 0, sensitive trace/body keys 0, no full order/tracking identifiers, no fact/number/status/entity drift, and complete model evidence. Then inspect all 50 buyer/reply pairs, record `approved` plus a short naturalness/conciseness/directness/boundary note for every row, and regenerate summary/report files. Any rejection requires a real source/fixture-rule fix and a complete new 50-case run.

- [ ] **Step 5: Write the comparison**

Include old `pa-1` versus new `pa-1`, representative tone-case before/after examples, per-style assertion distributions, sentence-count distribution, forbidden-template distribution, model evidence, and human-review outcome. Only customer-visible redacted messages/replies and safe metadata may appear.

### Task 7: Handoff, security review, publish to PR #97, and wait for checks

**Files:**
- Modify: `docs/development-handoff.md`
- Modify: report pointer/documentation if required by repository convention

- [ ] **Step 1: Update handoff**

Add a dated 2026-07-20 entry at the top describing the 50-case tone gate, unchanged fact/safety validator, final run ID, 50/50 result, and report paths.

- [ ] **Step 2: Run final verification from clean commands**

Repeat the affected, full, and `tests/contract` suites; validate the final summary and all 50 human-review rows; inspect `git diff --check` and `git status --short`.

- [ ] **Step 3: Run required secret checks**

Stage only scoped files, inspect `git diff --cached`, then run:

```bash
rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET" <staged-file-list>
```

Expected: no secret values; key-name references, if any, are reviewed as non-secret documentation only.

- [ ] **Step 4: Commit and push the existing branch**

Commit focused implementation/report changes, push `codex/acs-node-bound-grounded-rewrite`, and confirm PR #97 points to the new commit. Do not merge or deploy.

## Final acceptance record (2026-07-21)

The final accepted run is `reports/evals/acs-natural-customer-service-tone-20260721-r19.{jsonl,summary.json,conversations.json}` against snapshot hash `9128f2ef13710e6b826e271f`. The repository ignores `reports/`, so these metadata-only local artifacts remain audit evidence and are not force-added to Git.

| Run | Automated result | Evidence retained |
|---|---:|---|
| r12 | 50/50 | First automated hard pass; retained as pre-final evidence, not treated as final human acceptance. |
| r14 | 49/50 | `tone-15` failed required model-generation evidence. |
| r15 | 49/50 | `tone-16` exposed literal-only logistics next-step matching. |
| r16 | 49/50 | `tone-20` exposed a generated tracking reply that omitted the privacy boundary. |
| r17 | 49/50 | `tone-20` exposed the need for bounded semantic logistics-action matching with negation protection. |
| r18 | 50/50 | Automated hard pass; human review rejected unsupported restock notifications, delivered-status tracking advice, and a raw long listing title. |
| r19 | 50/50 | Final automated and 50-row human acceptance. |

r19 records `total_messages=50`, `passed=50`, `blocked=0`, `needs_review=0`, `all_messages_passed=true`, and `external_send=0`. Its 42 `candidate` rows have zero bad model-metadata rows: all use `deepseek-v4-pro`, `route_role=node_binding`, `status=succeeded`, `fallback_used=false`, and `validation_status=passed`; the remaining eight rows are intentional safety handoffs. All 50 customer-visible replies were reviewed and approved individually.

The accepted implementation addresses the complete evidence chain without weakening existing gates:

- natural customer-service Prompt and validator rules keep the model inside the deterministic fact boundary;
- product-audience replies remove source-explanation boilerplate and unrelated professional disclaimers;
- network retry is limited and bounded, while multiple typed context requests are consumed in sequence;
- tracking replies preserve an explicit privacy boundary, and logistics next steps use bounded semantic action/modifier matching with negation and narrative protections;
- model replies cannot invent restock reminder/notification capabilities absent from the deterministic source;
- delivered orders cannot be paired with continued-delivery or real-time tracking advice;
- order-item replies derive a natural short category from existing product/title evidence while preserving referenced entity IDs and without inventing an audience.

- [ ] **Step 5: Wait for required checks**

Use `gh pr checks 97 --watch` and report each required check's final status. If a check fails, inspect the failure, fix the real issue with TDD, rerun local gates, commit/push, and wait again.

## Plan self-review

- Spec coverage: all 11 design sections map to Tasks 1–7, including fixed provenance, 30+20 structure, explainable style gates, unchanged safety validators, baseline/final comparison, privacy, manual review, rollback-safe fixture separation, and PR checks.
- Placeholder scan: no `TBD`, `TODO`, “implement later”, or unspecified test command remains.
- Type consistency: fixture provenance remains under `generation`; per-turn declarations use `style_assertions` and `human_review`; generated row/summary evidence uses those same names; model evidence retains existing `model_version`, `route_role`, `status`, `fallback_used`, and `validation_status` keys.
