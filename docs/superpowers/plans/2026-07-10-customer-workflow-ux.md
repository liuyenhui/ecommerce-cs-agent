# Customer Workflow UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a customer operator create the first simulation from an empty store and understand the real AI decision blocker in plain Chinese.

**Architecture:** Extract deterministic trace-presentation decisions into a pure TypeScript module, then render them in the existing Customer Admin drawer and X6 graph. Reuse one simulation composer in both empty and populated message states. Preserve the two-column conversation workspace and Customer/System auth boundary.

**Tech Stack:** React 19, TypeScript 5.9, Vite 7, Vitest, AntV X6, existing CSS design tokens and native Node regression scripts.

---

### Task 1: Add executable trace-presentation tests

**Files:**
- Create: `admin-web/shared/trace-presentation.ts`
- Create: `admin-web/shared/trace-presentation.test.ts`
- Modify: `admin-web/package.json`
- Modify: `admin-web/package-lock.json`

- [ ] **Step 1: Install the focused test runner**

Run:

```bash
npm --prefix admin-web install --save-dev vitest@^3.2.4
```

Expected: `vitest` appears in `devDependencies` and the lockfile changes.

- [ ] **Step 2: Add the failing presentation tests**

Create `admin-web/shared/trace-presentation.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { presentDecisionState } from "./trace-presentation";

describe("presentDecisionState", () => {
  it("keeps waiting context on the context gate", () => {
    expect(presentDecisionState({ status: "waiting_context", missingContext: ["products"] })).toEqual({
      actionLabel: "需要补充资料",
      statusLabel: "等待资料",
      riskLabel: "-",
      currentNodeId: "context_gate",
      title: "等待补充资料",
      explanation: "缺少商品资料，补充后 AI 会继续判断。"
    });
  });

  it("presents a safe auto reply at the policy gate", () => {
    expect(presentDecisionState({ action: "auto_reply", status: "answer_ready", risk: "low" }).currentNodeId)
      .toBe("policy_gate");
  });
});
```

- [ ] **Step 3: Run the test and verify it fails**

Run:

```bash
npm --prefix admin-web exec vitest run shared/trace-presentation.test.ts
```

Expected: FAIL because `trace-presentation.ts` does not exist.

- [ ] **Step 4: Implement the minimal pure presenter**

Create `admin-web/shared/trace-presentation.ts` with exported `DecisionPresentationInput`, `DecisionPresentation`, raw-to-Chinese label maps, `contextLabel()`, and `presentDecisionState()`. The first branches must be:

```ts
if (status === "waiting_context" || action === "context_request") {
  const labels = missingContext.map(contextLabel).join("、") || "所需业务资料";
  return {
    actionLabel: "需要补充资料",
    statusLabel: "等待资料",
    riskLabel,
    currentNodeId: "context_gate",
    title: "等待补充资料",
    explanation: `缺少${labels}，补充后 AI 会继续判断。`
  };
}
if (action === "action_request") {
  return {
    actionLabel: "等待外部操作",
    statusLabel: "等待执行结果",
    riskLabel,
    currentNodeId: "action_gate",
    title: "等待外部操作",
    explanation: "外部系统完成操作并回传结果后，AI 才会继续。"
  };
}
```

Add explicit branches for `handoff`, `auto_reply`/`answer_ready`, and `candidate`.

- [ ] **Step 5: Run the focused test**

Run the command from Step 3.

Expected: PASS.

- [ ] **Step 6: Wire Vitest into the normal Admin test script**

Change `admin-web/package.json`:

```json
"test": "tsc --noEmit && vitest run shared/trace-presentation.test.ts && node --test scripts/admin-boundary.test.mjs && node scripts/assert-ui-regressions.mjs && node --test src/mobile-shell.test.mjs"
```

Run `npm --prefix admin-web test`; expected: PASS.

### Task 2: Make first simulation available in the empty state

**Files:**
- Create: `admin-web/customer-admin/src/SimulationComposer.tsx`
- Modify: `admin-web/customer-admin/src/App.tsx:553`
- Modify: `admin-web/customer-admin/src/styles.css`
- Test: `admin-web/scripts/admin-boundary.test.mjs`
- Test: `admin-web/scripts/assert-ui-regressions.mjs`

- [ ] **Step 1: Add the failing structural regression**

Add a check that extracts `MessageHistory` and asserts both the selected and empty branches render `SimulationComposer`:

```js
test("empty message history can start the first simulation", () => {
  const customerApp = readRelative("customer-admin/src/App.tsx");
  const messageHistory = sliceBetween(customerApp, "function MessageHistory", "function ChatBubble");
  assert.equal((messageHistory.match(/<SimulationComposer/g) || []).length, 2);
  assert.match(messageHistory, /还没有会话，先模拟一次客户咨询/);
  assert.match(messageHistory, /模拟咨询不会发送给真实买家/);
});
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
node --test admin-web/scripts/admin-boundary.test.mjs
```

Expected: FAIL because the reusable composer and empty-state copy are absent.

- [ ] **Step 3: Extract the reusable composer**

Create `SimulationComposer.tsx` with props:

```ts
type SimulationComposerProps = {
  value: string;
  loading: boolean;
  error: string;
  emptyState?: boolean;
  onChange: (value: string) => void;
  onSubmit: (event: React.FormEvent) => void;
};
```

Render a labeled textarea, inline `role="alert"` error, the safety note `模拟咨询不会发送给真实买家`, and one submit button named `模拟决策`.

- [ ] **Step 4: Use the component in both message states**

In `MessageHistory`:

```tsx
<SimulationComposer
  value={question}
  loading={loading}
  error={simulationError}
  emptyState={!selectedConversation}
  onChange={(value) => {
    setQuestion(value);
    setSimulationError("");
  }}
  onSubmit={simulate}
/>
```

For empty input, set `simulationError` to `请输入模拟客户问题`; preserve the input on API error; clear it only after a successful decision.

- [ ] **Step 5: Run Admin tests**

```bash
npm --prefix admin-web test
```

Expected: PASS.

### Task 3: Correct blocker selection and localize the decision drawer

**Files:**
- Modify: `admin-web/shared/trace-replay.tsx`
- Modify: `admin-web/shared/components.tsx`
- Modify: `admin-web/customer-admin/src/App.tsx:841`
- Modify: `admin-web/shared/styles/base.css`
- Modify: `admin-web/customer-admin/src/styles.css`
- Test: `admin-web/shared/trace-presentation.test.ts`
- Test: `admin-web/scripts/assert-ui-regressions.mjs`

- [ ] **Step 1: Add failing tests for all business states**

Add table-driven cases:

```ts
it.each([
  ["context_request", "waiting_context", "context_gate", "等待补充资料"],
  ["action_request", "action_request", "action_gate", "等待外部操作"],
  ["handoff", "handoff", "policy_gate", "转人工处理"],
  ["auto_reply", "answer_ready", "policy_gate", "可以安全回复"],
  ["candidate", "candidate", "policy_gate", "建议回复待确认"]
])("maps %s/%s", (action, status, node, title) => {
  const result = presentDecisionState({ action, status, risk: "medium" });
  expect(result.currentNodeId).toBe(node);
  expect(result.title).toBe(title);
});
```

- [ ] **Step 2: Run and verify failure**

```bash
npm --prefix admin-web exec vitest run shared/trace-presentation.test.ts
```

Expected: FAIL for any missing branch.

- [ ] **Step 3: Make `DecisionTraceReplay` consume the pure presenter**

Pass `action`, `risk`, and `missingContext` into the replay component, compute one presentation, and use `presentation.currentNodeId` before the last completed node. Replace the top raw metadata row with the business title and explanation. Keep thread and graph version in a `<details>` element named `技术详情`.

- [ ] **Step 4: Localize the drawer metrics**

Change `MessageTraceDrawer` to display `presentation.actionLabel`, `presentation.statusLabel`, and `presentation.riskLabel`; keep raw values in the metric `title` attribute.

- [ ] **Step 5: Add graph fallback semantics**

Keep the node timeline visible even when X6 import fails. Add a caught import branch that sets `graphUnavailable` and renders:

```tsx
{graphUnavailable ? <p className="inlineNotice">流程图暂时无法显示，请查看下方节点时间线。</p> : null}
```

- [ ] **Step 6: Run focused and full Admin tests**

```bash
npm --prefix admin-web exec vitest run shared/trace-presentation.test.ts
npm --prefix admin-web test
npm --prefix admin-web run build
```

Expected: PASS; both Customer and System builds succeed.

Also retain the existing login loading-state behavior in `shared/components.tsx`: while login or launch processing is active, render one `正在处理` status and hide secondary login actions so the user cannot start a competing authentication flow.

### Task 4: Browser-verify the customer workflow and commit

**Files:**
- All Customer Workflow UX files from Tasks 1–3.

- [ ] **Step 1: Start local API and Customer Admin**

```bash
.venv/bin/uvicorn ecommerce_cs_agent.api.app:app --host 127.0.0.1 --port 8000
npm --prefix admin-web run dev:customer
```

- [ ] **Step 2: Run the approved synthetic browser journey**

At 1440×900 and 390×844:

1. log in with local test-only credentials;
2. open Message History with no records;
3. submit `这件商品是什么材质？如果不合适可以退货吗？`;
4. verify a conversation appears;
5. open `决策路径`;
6. verify the headline is `等待补充资料`, current node is `上下文闸门`, and the missing item is `商品资料`;
7. verify no horizontal overflow.

Save screenshots only under `/tmp/ecommerce-cs-agent-ui-closure/` and inspect each image before accepting it.

- [ ] **Step 3: Stage, secret-scan, and commit**

```bash
git add admin-web/package.json admin-web/package-lock.json \
  admin-web/shared/trace-presentation.ts \
  admin-web/shared/trace-presentation.test.ts \
  admin-web/shared/trace-replay.tsx \
  admin-web/shared/components.tsx \
  admin-web/shared/styles/base.css \
  admin-web/customer-admin/src/App.tsx \
  admin-web/customer-admin/src/SimulationComposer.tsx \
  admin-web/customer-admin/src/styles.css \
  admin-web/scripts/admin-boundary.test.mjs \
  admin-web/scripts/assert-ui-regressions.mjs
git diff --cached --check
git diff --cached | rg -n 'sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET' || true
git commit -m "feat: clarify customer AI workflow"
```
