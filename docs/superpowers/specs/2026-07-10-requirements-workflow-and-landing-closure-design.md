# Requirements, AI Workflow, and Landing Page Closure Design

**Date:** 2026-07-10

**Status:** Approved

## 1. Goal

Close the remaining first-version gap across three connected surfaces:

1. prove every required behavior with deterministic and live tests;
2. make the Customer Admin show how one customer message moves through the AI decision workflow;
3. make the public landing page explain the product to a non-technical ecommerce operator in a few seconds.

The selected visual direction is the second generated concept, “流程故事”. The landing page must lead with a visible message journey, and the Customer Admin must provide the real product evidence behind that story.

## 2. Current Evidence and Confirmed Gaps

The 2026-07-10 baseline passed:

- 226 Python tests;
- 8 Admin Web boundary tests;
- 31 Admin UI regression assertions;
- 2 mobile-shell tests;
- 2 landing-page copy tests;
- Customer Admin and System Admin production builds;
- both architecture runtime validators.

Passing tests do not mean the user journey is complete. Current inspection confirmed these remaining gaps:

- A store with no message history cannot start its first simulation because the simulator is rendered only after a conversation already exists.
- A `waiting_context` decision can be summarized as “记录检查点：已完成” even though the business blocker is the context gate and the missing product context.
- The decision drawer leads with raw values such as `context_request`, `waiting_context`, `medium`, `thread_id`, and `graph_version`; these are useful for technical troubleshooting but are not the clearest first layer for a customer operator.
- The public landing page uses a blank skeleton illustration where it should show authentic product evidence.
- The landing page explains four steps, but the page does not visually connect a real buyer question to knowledge lookup, risk control, a safe reply, or a human handoff.
- The mobile landing page is readable but vertically inefficient: capability cards and the step section require excessive scrolling before the final value statement.
- Existing tests verify approved copy and structural boundaries but do not cover the first-simulation empty state, blocker selection, localized workflow summaries, or visual proof assets.

## 3. Product and Architecture Boundaries

### 3.1 Customer and System Admin independence

- Customer Admin remains on `admin.ecommerce-cs-agent-dev.fcihome.com` and calls only Customer Admin auth and business APIs.
- System Admin remains on `system-admin.ecommerce-cs-agent-dev.fcihome.com` and calls only System Admin auth and system APIs.
- No customer/system switcher, shared session, or cross-probing auth guard may be introduced.
- The public landing page must not expose a System Admin entrance or imply that `open_erp_agent` is the product identity authority.

### 3.2 Existing API contracts

- The UI work consumes the existing `message-traces`, `message-simulations`, and `trace.graph` contracts.
- No backend contract change is required for the first-simulation entry, workflow summary, localized labels, or landing-page story.
- If implementation uncovers a missing stable field, update OpenAPI and all coupled architecture documents in the same change before consuming it.

### 3.3 Visual language

- Public landing page: black, white, neutral gray, generous whitespace, plain-language AI customer-service narrative, restrained blue interaction accent.
- Logged-in Admin: dense IBM/Carbon-style enterprise console with hairline dividers, compact controls, readable tables, and low visual decoration.
- Real interface captures must replace fake skeletons and placeholder art.
- Do not fabricate customers, testimonials, performance percentages, revenue results, partner logos, or integration claims.

## 4. Customer Admin Workflow Design

### 4.1 First simulation from an empty store

The empty message workspace must contain a usable simulation composer, not only an empty-state explanation.

The empty state contains:

- title: `还没有会话，先模拟一次客户咨询`;
- short explanation that simulations never send a real buyer message;
- a textarea with a realistic product question example;
- one primary action: `模拟决策`.

Submitting creates the existing `source=simulation` decision, reloads message history, selects the new simulated conversation, and opens or prominently exposes its decision path. Loading disables duplicate submission. Empty input receives a persistent inline validation message as well as optional toast feedback.

### 4.2 Conversation workspace

The existing two-column workspace remains:

- left: search and conversation list;
- right: buyer/AI/human message timeline and simulator composer.

The main workspace does not add status filters, order filters, read-state labels, or technical graph metadata. The decision path remains an explicit action on a message or decision-only event.

### 4.3 Three-layer decision drawer

The drawer presents information in this order:

1. **Business result:** action, status, and risk using localized customer language.
2. **Current workflow state:** where the decision stopped, why it stopped, and what is needed next.
3. **Technical details:** thread, graph version, raw node data, and raw record available lower in the drawer or behind the existing raw-record action.

Localized examples:

| Raw value | Customer-facing label |
| --- | --- |
| `context_request` | 需要补充资料 |
| `waiting_context` | 等待资料 |
| `auto_reply` | 可自动回复 |
| `candidate` | 建议回复 |
| `handoff` | 转人工处理 |
| `action_request` | 等待外部操作 |
| `low` | 低风险 |
| `medium` | 中风险 |
| `high` | 高风险 |

Raw values remain available through `title`, accessible description, or the technical detail layer.

### 4.4 Correct blocker and current-node semantics

The workflow summary must distinguish the last persisted node from the current business blocker.

- `waiting_context` or `context_request`: highlight `context_gate`; show the missing context types and the next action.
- `action_request`: highlight `action_gate`; explain which external action is waiting.
- `handoff`: highlight `policy_gate`; explain the handoff reason.
- `answer_ready` or `auto_reply`: highlight the successful policy outcome and safe reply.
- `candidate`: highlight the candidate/policy outcome and explain why the answer is not automatically sent.
- failed node: highlight the failed node and expose a customer-safe error explanation.

`persist_trace` may be shown as completed, but it must not replace an earlier unresolved blocker as the headline current state.

### 4.5 Graph and mobile fallback

Desktop uses the existing X6 right-angle decision graph with business labels, clear taken/skipped branches, and reduced-motion support. Mobile uses a readable vertical workflow/timeline before or instead of the large canvas. Both views must express state with text and shape, not color alone.

## 5. Public Landing Page Design

### 5.1 Selected direction

Use the selected “流程故事” direction:

- headline: `看得见 AI 怎么回答，也看得见它为什么不回答。`;
- supporting explanation: product information grounds the answer; simulation checks the result; rules and risk controls decide whether it can be sent;
- primary action: `进入客户后台`;
- secondary action: `查看演示流程`;
- authentic product proof showing a buyer question and the business workflow.

The page must not claim an anonymous interactive simulation. `进入客户后台` remains the primary CTA because simulation requires Customer Admin login; `查看演示流程` scrolls to the public demonstration story.

### 5.2 Hero proof

Replace the skeleton browser illustration with a current, sanitized capture of the real Customer Admin message workspace and decision path.

The capture must:

- use synthetic demo data only;
- contain no password, Cookie, Secret, authorization header, private buyer data, or real customer content;
- show customer question, workflow state, and safe outcome or blocker;
- omit transient login-success toasts and unrelated browser UI;
- remain legible at desktop and mobile landing-page sizes.

### 5.3 Workflow story

The public story uses customer language:

1. 客户提问
2. 查商品资料
3. 检查规则与风险
4. 安全回复或转人工

The flow explicitly states: `缺资料就先补资料，不让 AI 猜。`

The page should show one path in depth instead of repeating the same four features in multiple card grids.

### 5.4 Reassurance section

Use three typography-led rows or columns:

- `资料有依据` — replies use reviewed product, order, logistics, and rule context;
- `回复有规则` — price, refund, and risk rules decide whether automatic sending is allowed;
- `风险可转人工` — uncertain or high-risk cases do not force an AI answer.

No fabricated metrics are required for the first version.

### 5.5 Mobile behavior

- Hero copy, CTA, and proof remain visible without horizontal scrolling at 390×844.
- The workflow becomes a compact vertical sequence.
- Capability explanations use rows and dividers rather than three oversized empty cards.
- Images remain readable and are not stretched or reduced to illegible text.

## 6. Requirements-to-Test Closure

Create the traceable test matrix in `docs/requirements-test-matrix.md`. Each first-version requirement maps to:

- requirement source;
- positive path;
- denial/error path;
- automated test file and test name;
- live smoke step where applicable;
- current status and evidence.

Minimum new or extended coverage:

### 6.1 Deterministic backend tests

- real conditional graph branches and skipped-node statuses;
- approved low-risk knowledge can reach safe auto reply;
- missing product/order/logistics/rule context requests the correct typed context;
- context refill resumes the same decision thread/checkpoint;
- action results cannot claim success before an external success result;
- high-risk and incomplete-context paths do not auto-send;
- simulation creates trace data and never attempts external sending.

### 6.2 Frontend structural and component tests

- an empty message workspace contains the simulation form and submit action;
- the first successful simulation produces a selectable conversation;
- workflow status and risk values are localized without losing raw values;
- `waiting_context` selects the context blocker instead of `persist_trace`;
- missing context names appear in the blocker explanation;
- reduced-motion behavior disables animated flow edges;
- landing page contains the selected workflow story and a real proof asset reference;
- Customer/System auth and navigation boundaries remain isolated.

### 6.3 Browser journey tests

At minimum cover:

1. public landing page at 1440×900 and 390×844;
2. Customer Admin login and auth guard;
3. empty message history to first simulation;
4. conversation selection and decision drawer;
5. context-request blocker presentation;
6. mobile navigation, simulator, and decision timeline;
7. no horizontal overflow;
8. Customer host calls only `/v1/admin/auth/me` and never exposes System Admin entry.

Browser artifacts must use synthetic data and temporary `0600` storage state when login state is required.

### 6.4 Release and live gates

The release is not complete until all of these pass:

- full Python suite;
- Admin Web tests, landing tests, TypeScript check, and both builds;
- architecture validators;
- Helm lint and template validation;
- targeted sensitive-pattern scan of staged changes;
- PR checks and CodeQL SAST;
- image publication through GitHub Actions, not local `docker push`;
- GitOps reconciliation and rollout;
- API, Customer Admin, and System Admin `/health` checks;
- public landing and Customer Admin desktop/mobile live smoke;
- first simulation and decision-path live smoke with approved non-secret test state.

## 7. Error Handling and Safety

- Simulation validation errors stay near the form and are not lost in a transient toast.
- Loading state prevents duplicate decisions.
- API failures preserve the current typed question and show a retryable explanation.
- Graph rendering failure falls back to the node timeline rather than a blank drawer.
- Technical identifiers and raw records remain available for support without dominating the customer-facing hierarchy.
- No live password, Cookie, storage state, Secret, kubeconfig content, private customer data, or token-bearing output enters screenshots, logs, docs, commits, or PR text.

## 8. Implementation Decomposition

The implementation plan will assign independently reviewable tasks:

1. Requirements/test matrix and missing backend coverage.
2. Empty-state first simulation and browser journey test.
3. Decision blocker semantics, localization, and graph/timeline accessibility.
4. Landing-page “流程故事” implementation with sanitized real product proof.
5. Responsive and visual QA at required viewports.
6. Full regression, secret scan, PR, publish, GitOps deploy, and live smoke closure.

Existing uncommitted LangGraph branch execution, checkpointer, auto-reply, and X6 replay improvements are explicitly included in this work and must be reviewed and submitted with the implementation rather than discarded.

## 9. Acceptance Criteria

The work is complete only when:

- every first-version requirement has a test-case mapping and current result;
- all deterministic suites and builds pass;
- an empty Customer Admin store can create its first simulation;
- the workflow headline identifies the unresolved business blocker and next action correctly;
- customer-facing workflow labels are plain Chinese while technical values remain available for support;
- the public page uses authentic product proof and explains the message journey without invented claims;
- desktop and mobile views have no horizontal overflow and maintain readable hierarchy;
- customer/system boundaries and session isolation remain unchanged;
- the approved commit is merged, published, deployed through GitOps, and verified on live dev hosts.
