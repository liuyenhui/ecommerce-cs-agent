# ACS Grounded Natural Replies Design

## Goal

Replace typed-context JSON dumps with concise, customer-facing Chinese replies and close the simulation false-positive gap. The fixed 10-conversation, 30-turn suite only passes when every non-handoff turn answers the current buyer question with a grounded natural-language response.

## Root Cause

`ReplyDecisionGraph._generate_candidate()` currently prefers `_context_grounded_reply()` whenever typed context exists. That helper serializes all product, order, and logistics rows as JSON, so the configured reply provider is bypassed. The simulation evaluator then accepts those dumps because it only searches for expected fact strings, which are naturally present in the JSON.

## Selected Design

### Grounded reply composer

Introduce a focused deterministic composer at the decision-graph boundary. It receives the current buyer message, accumulated conversation history, and typed product/order/logistics context, then returns one of:

- a concise Chinese candidate reply using only the relevant snapshot entity;
- a safe uncertainty reply when the snapshot lacks the requested fact;
- a handoff signal for high-risk operations or claims that require human judgment.

The composer will classify the current question into the existing supported intents: audience/applicability, specification, usage, price, promotion, stock, listing status, comparison, order status, purchased item, carrier, logistics status, tracking-number privacy, delivery-time certainty, and unsupported medical/usage claims. It will resolve explicit IDs and masked suffixes first, then use conversation history for pronouns and product/order switching. It must never dump the complete context collection or expose internal source references.

The existing `ReplyProvider` remains the knowledge-answer fallback. A future configured LLM may polish the grounded draft, but the correctness path does not depend on the currently unauthorized DeepSeek credential.

### Safety behavior

- Medical treatment guarantees, unsupported dosage/frequency, guaranteed arrival times, and requests to invent facts produce an explicit limitation and human-handoff recommendation.
- Full tracking identifiers are never returned; only already-masked snapshot values may appear.
- Ambiguous entity matches do not select the first row. The reply asks the buyer to provide a product ID or masked order suffix.
- Simulation remains assist-only and keeps `external_send.attempted=false`.

### Evaluation gate

Extend the evaluator with independent assertions:

- response is non-empty customer-facing Chinese text, not JSON, Python repr, XML, or a context/schema dump;
- response length stays within a customer-service range and does not enumerate unrelated entities;
- required facts are present in natural text and prohibited facts/claims are absent;
- the answer type matches the current question (price, stock, order, logistics, limitation, or handoff);
- explicit and historical references resolve to the expected product/order only;
- unsupported or ambiguous questions cannot pass with a generic snapshot payload;
- score derives from these assertions rather than assigning 5.0 whenever the old hard rules pass.

Reports will include a safe buyer-question/final-reply pair for every turn so human review can verify conversational quality without inspecting internal trace payloads.

## Data Flow

1. `reply-decisions` classifies intent and requests missing typed context.
2. Open ERP refills product/order/logistics snapshots on the same decision.
3. The graph resumes, resolves the relevant entity from the current turn plus history, and composes a grounded reply.
4. Policy gate returns `candidate` in simulation or `handoff` for high-risk/unsupported cases.
5. Eval validates contract, trace, no-send, grounding, entity resolution, natural language, relevance, and safety.

## Testing

Use TDD for each behavior:

1. Add failing unit tests proving typed context no longer becomes JSON and each supported intent returns the expected grounded wording.
2. Add evaluator tests that reject the previously accepted JSON payload, generic disclaimers, unrelated entity lists, fabricated values, and unsupported guarantees.
3. Re-run affected service/eval tests, then the full Python suite and contract checks.
4. Start the real K3s-backed local ACS path and run the unchanged 10-group/30-turn fixture.
5. Acceptance requires 30/30 with readable Chinese final replies, zero blocked/needs-review, complete traces, zero external sends, and a human-readable conversation report.

## Compatibility

No public path or schema changes are required. `POST /v1/reply-decisions` and typed context refill endpoints remain unchanged; only candidate content and eval strictness change.
