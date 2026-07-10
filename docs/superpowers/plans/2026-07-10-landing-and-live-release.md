# Landing Page and Live Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the selected “流程故事” landing page with authentic product proof, then publish and verify the entire approved change on dev.

**Architecture:** Keep the public page in the existing Customer Admin bundle and reuse current navigation/auth behavior. Replace the fake preview with a sanitized static capture generated from the real local Customer Admin workflow. Finish through the protected-main PR, image workflow, GitOps release gate, and live desktop/mobile smoke.

**Tech Stack:** React 19, TypeScript, Vite, CSS, Lucide icons, Playwright/Chrome capture, GitHub Actions, Helm, Flux/GitOps, Kubernetes.

---

### Task 1: Lock the selected landing narrative with failing tests

**Files:**
- Modify: `admin-web/scripts/landing-page-copy.test.mjs`
- Modify: `admin-web/scripts/assert-ui-regressions.mjs`
- Modify: `admin-web/customer-admin/src/App.tsx:232`

- [ ] **Step 1: Replace the old copy expectations with the approved story**

Use this exact expected list:

```js
const expectedText = [
  "看得见 AI 怎么回答，也看得见它为什么不回答。",
  "缺资料就先补资料，不让 AI 猜。",
  "客户提问",
  "查商品资料",
  "检查规则与风险",
  "安全回复或转人工",
  "资料有依据",
  "回复有规则",
  "风险可转人工",
  "进入客户后台",
  "查看演示流程"
];
```

Add an assertion that `previewLine`, `previewTable`, and `previewNav` are absent from `CustomerLanding`.

- [ ] **Step 2: Run the landing test and verify it fails**

```bash
npm --prefix admin-web run test:landing
```

Expected: FAIL on the new headline and fake-preview removal.

### Task 2: Implement the “流程故事” landing page

**Files:**
- Modify: `admin-web/customer-admin/src/App.tsx:232`
- Modify: `admin-web/shared/styles/base.css:123`
- Modify: `admin-web/customer-admin/src/styles.css`

- [ ] **Step 1: Replace the hero copy and actions**

Keep the existing authenticated destination logic and render:

```tsx
<p className="landingEyebrow">可控 AI 客服工作流</p>
<h1>看得见 AI 怎么回答，也看得见它为什么不回答。</h1>
<p className="heroSubtitle">
  商品资料给 AI 依据，模拟问答先检查效果，规则和风险控制决定自动回复还是转人工。
</p>
```

Primary CTA remains `进入客户后台`; secondary CTA scrolls to `#demo-flow`.

- [ ] **Step 2: Replace repeated feature cards with one workflow story**

Render four items with these titles and descriptions:

```ts
const publicWorkflow = [
  ["客户提问", "收到买家的商品、订单或售后问题。"],
  ["查商品资料", "检索已审核的商品、订单、物流和规则；缺资料就先补资料，不让 AI 猜。"],
  ["检查规则与风险", "价格、退款和高风险表达必须通过规则闸门。"],
  ["安全回复或转人工", "满足条件才自动回复，不确定时给建议或转人工。"]
] as const;
```

- [ ] **Step 3: Add the three reassurance rows**

Render `资料有依据`, `回复有规则`, and `风险可转人工` as typography-led rows with Lucide icons and dividers, not equal-height marketing cards.

- [ ] **Step 4: Run tests**

```bash
npm --prefix admin-web run test:landing
npm --prefix admin-web test
```

Expected: PASS.

### Task 3: Generate and validate authentic product proof

**Files:**
- Create: `admin-web/customer-admin/public/ai-workflow-proof.png`
- Modify: `admin-web/customer-admin/src/App.tsx`
- Modify: `admin-web/scripts/landing-page-copy.test.mjs`

- [ ] **Step 1: Capture the fixed local workflow with synthetic data**

Use the approved local browser journey from the Customer Workflow plan. Before capture:

- close the login-success toast;
- open one synthetic decision drawer;
- ensure the business blocker headline and graph are visible;
- crop to the Customer Admin product surface only;
- capture at a scale that remains readable inside the hero.

Save the accepted PNG directly as `admin-web/customer-admin/public/ai-workflow-proof.png`.

- [ ] **Step 2: Inspect the saved PNG**

Open the exact saved file and reject it if it contains a password, Cookie, Secret, real buyer data, loading state, toast, crop error, or unreadable workflow labels.

- [ ] **Step 3: Render the proof asset**

Replace the fake preview with:

```tsx
<figure className="workflowProof">
  <img
    src="/ai-workflow-proof.png"
    alt="客户问题经过资料检索、规则检查并停在资料补充步骤的真实客户后台"
  />
  <figcaption>缺资料就先补资料，不让 AI 猜。</figcaption>
</figure>
```

- [ ] **Step 4: Add an asset regression assertion**

In `landing-page-copy.test.mjs`, assert that the source references `/ai-workflow-proof.png`, the file exists, begins with the PNG signature, and is larger than 20 KB.

- [ ] **Step 5: Build**

```bash
npm --prefix admin-web run build
```

Expected: both bundles succeed and the proof asset is present in the Customer build output.

### Task 4: Desktop/mobile visual QA and accessibility checks

**Files:**
- Modify if evidence requires: `admin-web/shared/styles/base.css`
- Modify if evidence requires: `admin-web/customer-admin/src/styles.css`

- [ ] **Step 1: Capture the local public page**

Capture full-page screenshots at 1440×900 and 390×844 into `/tmp/ecommerce-cs-agent-ui-closure/`.

- [ ] **Step 2: Inspect both screenshots against the selected second concept**

Verify:

- the workflow story is the first product proof;
- the hero has one dominant CTA;
- the proof is authentic and legible;
- mobile uses a compact vertical flow and avoids oversized empty cards;
- there is no horizontal overflow, clipped copy, stretched image, or illegible text.

- [ ] **Step 3: Run DOM accessibility checks**

Verify unique `h1`, ordered heading levels, descriptive image alt text, visible keyboard focus, button target size, and reduced-motion behavior.

- [ ] **Step 4: Re-run frontend verification**

```bash
npm --prefix admin-web test
npm --prefix admin-web run test:landing
npm --prefix admin-web run build
```

Expected: PASS.

### Task 5: Full repository verification and landing commit

**Files:**
- All landing and proof files from Tasks 1–4.

- [ ] **Step 1: Run the full local gate**

```bash
PATH=.venv/bin:$PATH python -m pytest
npm --prefix admin-web test
npm --prefix admin-web run test:landing
npm --prefix admin-web run build
node docs/scripts/validate-x6-architecture-runtime.mjs
node docs/scripts/validate-business-flow-x6-labels.mjs
helm lint deploy/helm/ecommerce-cs-agent -f deploy/helm/ecommerce-cs-agent/values-dev.yaml
helm template ecommerce-cs-agent deploy/helm/ecommerce-cs-agent \
  -n ecommerce-cs-agent-dev \
  -f deploy/helm/ecommerce-cs-agent/values-dev.yaml >/tmp/ecommerce-cs-agent-rendered.yaml
python scripts/check_k8s_security.py
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Stage and secret-scan the landing slice**

```bash
git add admin-web/customer-admin/src/App.tsx \
  admin-web/customer-admin/src/styles.css \
  admin-web/customer-admin/public/ai-workflow-proof.png \
  admin-web/shared/styles/base.css \
  admin-web/scripts/landing-page-copy.test.mjs \
  admin-web/scripts/assert-ui-regressions.mjs
git diff --cached --check
python scripts/check_sensitive_patterns.py .
git diff --cached | rg -n 'sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET' || true
```

Expected: no secret or private-data match.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: explain the visible AI customer workflow"
```

### Task 6: Publish through protected main and verify dev

**Files:**
- No new source files unless CI or live evidence exposes a defect.

- [ ] **Step 1: Review the complete branch scope**

```bash
git status --short --branch
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
```

Expected: branch contains the authorized local debug profile, decision runtime, workflow UX, landing, tests, and plan/spec commits; `.codegraph/` and temporary screenshots are absent.

- [ ] **Step 2: Push the current branch**

```bash
git push -u origin HEAD
```

- [ ] **Step 3: Open a draft PR and watch required checks**

Create a draft PR to `main`. Wait for `PR Checks` and `CodeQL SAST`. If either fails, use `github:gh-fix-ci` before changing code.

- [ ] **Step 4: Mark ready and merge after green checks**

Confirm the PR diff contains no secrets or unrelated `.codegraph` files, mark ready, and merge through protected main.

- [ ] **Step 5: Verify image and GitOps workflows**

Watch `Publish Images` for the merge SHA, then `Deploy Dev GitOps`. Record the publish run ID, deploy run ID, image tag `sha-${HEAD_SHA:0:12}`, and GitOps commit from workflow outputs.

- [ ] **Step 6: Verify live release evidence**

Confirm:

```bash
curl -fsS https://api.ecommerce-cs-agent-dev.fcihome.com/health
curl -fsS https://admin.ecommerce-cs-agent-dev.fcihome.com/health
curl -fsS https://system-admin.ecommerce-cs-agent-dev.fcihome.com/health
```

Then run the approved live Customer Admin smoke without printing credentials or cookies:

1. public landing desktop and mobile;
2. customer login and `/v1/admin/auth/me` only;
3. first simulation from empty state;
4. decision path shows the correct context blocker;
5. System Admin entry is absent from the Customer host;
6. no horizontal overflow at 390×844.

- [ ] **Step 7: Fix and repeat until the live gate passes**

Any live defect returns to a failing automated reproduction before the minimal fix. Repeat local gate, PR checks, publish, deploy, and smoke until every acceptance item passes.

