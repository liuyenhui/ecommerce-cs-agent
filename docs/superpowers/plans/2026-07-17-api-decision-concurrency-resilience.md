# API Decision Concurrency and Resilience Implementation Plan

> **Execution rule:** implement each task test-first, keep secrets out of command output and Git, and stop deployment if any release gate fails.

**Goal:** Prevent synchronous LangGraph/LLM execution from blocking FastAPI health handling, eliminate batch-simulation 502/503 responses, and restore the Dev rollout blocked by the missing credential-encryption Secret.

**Architecture:** Route every synchronous decision-graph entrypoint through one process-local `BoundedDecisionExecutor` backed by `anyio.to_thread.run_sync` and a shared capacity limiter. Keep `/health` dependency-free and asynchronous. Add explicit Kubernetes probe budgets and two Dev API replicas as secondary resilience controls.

**Tech stack:** Python 3.12+, FastAPI, AnyIO, pytest, Helm, Kubernetes, GitHub Actions.

---

## Task 1: Add bounded synchronous decision execution

**Files:**

- Create: `ecommerce_cs_agent/services/decision_execution.py`
- Create: `tests/services/test_decision_execution.py`
- Modify: `ecommerce_cs_agent/core/config.py`
- Create: `tests/core/test_config.py`
- Modify: `pyproject.toml`

1. Add failing tests proving executor work runs outside the event-loop thread and peak concurrency never exceeds its limit.
2. Add failing settings tests for default `4`, a valid override, and rejection of zero, negative, and non-integer values.
3. Run the focused tests and confirm the expected failures.
4. Implement `BoundedDecisionExecutor` with `anyio.to_thread.run_sync` and a shared `CapacityLimiter`.
5. Add `decision_max_concurrency` to `Settings` and parse `DECISION_MAX_CONCURRENCY` as a positive integer.
6. Declare AnyIO as a direct runtime dependency.
7. Run focused tests and confirm they pass.

## Task 2: Offload every decision-graph API entrypoint

**Files:**

- Modify: `ecommerce_cs_agent/api/app.py`
- Create: `tests/api/test_decision_concurrency.py`

1. Add failing API tests with a fake decision service that records whether it was invoked on the event-loop thread.
2. Cover reply creation, typed context refill, action result submission, and Admin message simulation.
3. Add a regression assertion that `/health` is an asynchronous route and remains responsive while decision work is blocked in a worker thread.
4. Run focused tests and confirm the expected failures.
5. Add a test-only decision service override, guarded consistently with the existing test overrides.
6. Instantiate one shared executor per app and use it for all four decision graph entrypoints.
7. Convert `/health` to `async def` without adding dependency checks.
8. Run API tests and confirm they pass.

## Task 3: Harden Helm runtime settings and probes

**Files:**

- Modify: `deploy/helm/ecommerce-cs-agent/values.yaml`
- Modify: `deploy/helm/ecommerce-cs-agent/values-dev.yaml`
- Modify: `deploy/helm/ecommerce-cs-agent/values.schema.json`
- Modify: `deploy/helm/ecommerce-cs-agent/templates/api-deployment.yaml`
- Modify: `tests/deploy/test_deploy_artifacts.py`

1. Add failing deployment tests for `DECISION_MAX_CONCURRENCY`, explicit startup/readiness/liveness timings, and two Dev API replicas.
2. Run focused deployment tests and confirm the expected failures.
3. Add the Helm value and schema validation with a minimum of one.
4. Render the environment variable and explicit probe budgets in the API Deployment.
5. Set Dev API replicas to two.
6. Run focused tests, Helm lint, and Helm template.

## Task 4: Restore the blocked Dev deployment Secret

**Runtime scope:** namespace `ecommerce-cs-agent-dev`.

1. Generate a fresh random 32-byte value and encode it as base64 without printing it.
2. Create/update Secret `ecommerce-cs-agent-llm-credential-encryption` with key `master-key` through stdin.
3. Clear the local shell variable immediately.
4. Verify only the Secret name and key name, never its value.
5. Confirm the blocked Deployment can create containers; keep node-level LLM binding disabled.

## Task 5: Update operational documentation

**Files:**

- Modify: `docs/deployment.md`
- Modify: `docs/testing-strategy.md`
- Modify: `docs/requirements-test-matrix.md`
- Modify: `docs/development-handoff.md`

1. Document the event-loop isolation boundary, concurrency setting, probe intent, and Secret recovery rule.
2. Add regression and live-smoke evidence requirements.
3. Add a dated handoff entry describing API, deployment, and test scope.
4. Run documentation-specific assertions and `git diff --check`.

## Task 6: Verify, publish, deploy, and live-test

1. Run the full Python suite.
2. Run Helm lint/template and Kubernetes security checks.
3. Run architecture validators if the architecture HTML changed.
4. Review the diff and run the targeted staged-secret scan before committing or pushing.
5. Commit, push `codex/fix-api-event-loop-502`, open a PR, and monitor required checks.
6. Fix any review or CI failure in scope, then merge only after all gates pass.
7. Publish API/Admin images through GitHub Actions and deploy through the existing Dev GitOps workflow.
8. Record API Pod restart counts, run 30 simulation-only requests with concurrent `/health` polling, and re-check restart counts.
9. Acceptance requires zero request `5xx`, zero health failures, zero new API restarts, and no external sends.
