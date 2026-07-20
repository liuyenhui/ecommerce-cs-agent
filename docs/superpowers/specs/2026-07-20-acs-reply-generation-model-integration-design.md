# ACS Reply Generation Model Integration Design

## Goal

Connect the ACS decision chain to the governed `reply_generation` model route so customer replies are naturally phrased by a real model while product, price, stock, order, logistics, privacy, and handoff decisions remain deterministic and auditable.

## Current Gap

System Admin already persists Provider configuration, released scenario routes, primary/fallback models, invocation policy, and metrics. The runtime reply path does not consume those records: `DecisionService` defaults to `DeterministicReplyProvider`, while grounded typed context is rendered directly by `grounded_reply.py`. Consequently the current safe replies are correct but repetitive and template-like.

## Selected Architecture

### 1. Runtime route resolver

Add a read-only runtime repository that resolves the organization’s single `running` LLM release and its enabled `reply_generation` route. It returns:

- scenario route ID;
- primary Provider endpoint, Secret reference, and model;
- optional fallback Provider and model;
- temperature, maximum output tokens, timeout, retries, circuit-breaker threshold, and recovery interval.

The resolver must scope by `organization_id`; a store may only use its organization’s released route. Draft, pending, superseded, rolled-back, disabled, unhealthy, or cross-organization routes are not callable. If no released route is available, the decision chain uses the deterministic grounded composer.

### 2. Secure OpenAI-compatible client

Implement an OpenAI-compatible chat-completions client for the Provider route. Provider credentials are resolved through the existing exact Secret-reference/origin allowlist boundary. Runtime Secret values remain in memory only and never enter request traces, API responses, database rows, reports, or logs.

The client enforces:

- HTTPS origin validation and existing pinned-IP/TLS protections;
- absolute timeout, bounded response size, configured retry limit, and no redirects;
- primary then configured fallback routing;
- stable safe error codes rather than response-body logging;
- circuit-breaker state per Provider/model route.

Local ACS debug may use the generated `0600` runtime environment only for the exact configured runtime Provider tuple. Production continues to use Kubernetes Secret references.

### 3. Grounded prompt contract

The existing composer continues to determine intent, relevant entities, factual answer fields, privacy decisions, and handoff outcome. Only safe candidate outcomes are sent to the model for phrasing.

The model input contains an allowlisted structured payload:

- current buyer question;
- minimal recent dialogue required for tone and pronoun continuity;
- deterministic draft reply;
- relevant product/order/logistics facts only;
- explicit safety constraints and prohibited claims.

It excludes full snapshots, unrelated entities, raw internal source references, full order/tracking identifiers, buyer name, phone, address, cookies, tokens, and credentials.

The model must return strict JSON:

```json
{
  "reply_text": "可以的，这款比熊可以用。皮肤比较敏感的话，建议先小范围试用。"
}
```

The model may improve wording only. It may not change action, handoff reason, selected entity IDs, prices, promotion prices, stock, order state, carrier, logistics state, or masked identifiers.

### 4. Output validation and fallback

After model generation, validate:

- JSON schema and reply length;
- customer-facing Chinese natural language;
- required deterministic facts are preserved;
- no new numbers, statuses, carriers, product/order entities, medical claims, arrival guarantees, or unmasked identifiers appear;
- no instruction/prompt/schema leakage;
- handoff and privacy policy remain unchanged.

If the model times out, returns 401/429/5xx, produces invalid JSON, changes facts, or fails safety checks, discard the model output and use the deterministic grounded draft. Model failure must not turn a safe candidate into an unsafe reply or block the customer-service decision.

### 5. Decision-chain integration

`ReplyDecisionGraph` will generate the deterministic grounded outcome first. For a non-handoff candidate, it asks the runtime model provider to rewrite that draft. The final candidate preserves deterministic evidence and referenced entity IDs while trace records only the model version, route role, latency/status reference, and whether fallback was used.

Simulation remains `source=simulation` with `external_send.attempted=false`; it does call the configured model so the evaluated text matches the production generation path.

### 6. Metrics and privacy

Each attempted call writes `llm_invocation_metric` with scenario route, route role, organization/store, token counts, latency, status, safe error code, estimated cost, and currency when available. It must not persist Prompt, buyer content, model response, Authorization header, or Secret value.

## Testing and Acceptance

Use TDD and retain the existing strict natural-language evaluator.

1. Route tests: released organization route selection, fallback selection, missing/disabled/cross-organization rejection.
2. Client tests: request shape, strict JSON parsing, timeout/retry/circuit breaker, HTTP errors, Secret redaction, and bounded response.
3. Grounding tests: model rewrites style without changing facts; fabricated price/status/carrier, extra entities, medical claims, arrival guarantees, and unmasked tracking values are rejected.
4. Decision tests: successful model reply, primary-to-fallback, deterministic fallback, unchanged handoff, trace/metric privacy.
5. Full Python and OpenAPI contract tests.
6. Real K3s-backed ACS evaluation using a valid released `reply_generation` Provider route. The unchanged 10-group/30-turn suite must pass with no JSON dumps, no factual changes, no blocked/needs-review, complete trace, and zero external sends.
7. Human review of all 30 buyer/reply pairs for naturalness, brevity, directness, and consistency with a real ecommerce customer-service agent.

## Compatibility

Public reply-decision and typed-context endpoints remain unchanged. The existing deterministic composer remains the safety fallback. No customer-facing API field is added solely for model internals.
