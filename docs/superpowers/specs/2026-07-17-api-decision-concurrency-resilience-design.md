# API Decision Concurrency and Resilience Design

## Goal

Prevent slow synchronous LangGraph and LLM calls from blocking the FastAPI event loop, causing Kubernetes health probe failures, API Pod restarts, and Customer Admin `502` responses during simulation batches.

## Confirmed Failure Mechanism

The decision routes are asynchronous because they read request bodies with `await request.json()`, but they call the synchronous `DecisionService` directly. The real LLM adapters perform blocking DNS, socket, TLS, and response reads with absolute deadlines. A single Uvicorn worker therefore cannot serve `/health` while the decision graph is inside a model call. With the current one-second probes, sustained decision traffic reaches the liveness failure threshold and Kubernetes terminates the only API Pod.

The public Traefik, FRPS, K3s FRPC, Ingress, database, and node resources are not the failing boundary. They only surface the API Pod disappearance as `502` or `503`.

## Selected Design

### Bounded decision execution

Add a small `BoundedDecisionExecutor` that accepts a synchronous callable and executes it with `anyio.to_thread.run_sync`. A shared `CapacityLimiter` bounds concurrent calls per API process. `DECISION_MAX_CONCURRENCY` defaults to `4`, must be a positive integer, and is rendered explicitly by Helm.

Use the executor for every async route that can run or resume the decision graph:

- create reply decision;
- typed context refill;
- action result submission;
- Customer Admin message simulation.

Repository and domain exceptions must continue to be translated by the existing route handlers. Queued calls wait for executor capacity without occupying the event loop or the AnyIO worker pool.

### Health and deployment resilience

Make `/health` an `async def` endpoint containing no external dependency checks. This keeps liveness independent from the worker thread pool.

Render explicit probes:

- startup: two-second period, 30 failures;
- readiness: two-second timeout, five-second period, three failures;
- liveness: two-second timeout, ten-second period, six failures.

The probe budget is secondary protection, not the primary fix. Dev runs two API replicas so a restart or rollout does not remove the entire API service.

### Credential-encryption Secret recovery

The PR #87 chart requires Secret `ecommerce-cs-agent-llm-credential-encryption`, key `master-key`. Its value is a base64 string that decodes to exactly 32 random bytes. Create it directly in `ecommerce-cs-agent-dev` without printing, storing, or committing the value. Keep `LLM_NODE_BINDING_ENABLED=false` until the rollout and connection tests pass.

## Failure Handling

- LLM/provider deadlines and deterministic fallbacks remain unchanged.
- Executor capacity limits model pressure but does not return a new API status or change idempotency behavior.
- Cancellation does not forcibly kill a running synchronous thread; the existing absolute provider deadline remains the upper bound.
- Secret absence remains fail-closed. The deployment must not make the reference optional or generate a different key per replica.

## Verification

- Unit test that the executor runs work outside the event-loop thread.
- Unit test that concurrent work never exceeds its configured limit.
- API regression test that decision routes use the executor and `/health` is asynchronous.
- Settings tests for default, valid override, zero, negative, and non-integer concurrency.
- Helm tests for the concurrency environment variable, explicit probes, and two Dev replicas.
- Full Python, Helm lint/template, and existing architecture validators.
- Dev smoke test: 30 simulation requests with concurrent API health polling; require zero API restarts, zero `5xx`, `/health` success throughout, and simulation-only external-send behavior.

## Non-goals

- Rewriting the full LangGraph and provider stack to native async in this patch.
- Changing service-stage rules or LLM prompts.
- Recording Secret values, model prompts, cookies, or authorization headers.
