# Admin 上海时区中文时间显示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Customer Admin 与 System Admin 的用户可见时间统一显示为 `Asia/Shanghai` 中文格式，同时保持 API、数据库和筛选协议不变。

**Architecture:** 在 `admin-web/shared` 增加唯一的纯格式化入口，并由共享 DataTable 自动处理时间字段；各页面的自定义时间展示显式调用同一入口。原始 JSON、API 参数和 `datetime-local` 输入继续保留协议值。

**Tech Stack:** React 18、TypeScript、Vitest、Testing Library、Vite、`Intl.DateTimeFormat`

---

### Task 1: 建立共享时间格式化契约

**Files:**
- Create: `admin-web/shared/date-time.test.ts`
- Create: `admin-web/shared/date-time.ts`
- Modify: `admin-web/package.json`

- [ ] **Step 1: Write the failing test**

新增测试，断言 `2026-07-17T16:30:45Z` 显示为 `2026年7月18日 00:30:45`，空值与非法值显示 `—`，并断言 `created_at`、`timestamp` 是时间字段而普通 ID 不是。

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix admin-web test -- --run shared/date-time.test.ts`
Expected: FAIL，因为共享时间模块尚不存在。

- [ ] **Step 3: Write minimal implementation**

使用固定 `timeZone: "Asia/Shanghai"`、`locale: "zh-CN"` 和 `formatToParts()` 实现 `formatShanghaiDateTime()`；实现 `isDateTimeField()` 供表格识别时间字段。

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix admin-web test -- --run shared/date-time.test.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

Run: `git add admin-web/shared/date-time.ts admin-web/shared/date-time.test.ts admin-web/package.json && git commit -m "feat: add Shanghai admin time formatter"`

### Task 2: 覆盖共享表格与租户层级列表

**Files:**
- Modify: `admin-web/shared/data.tsx`
- Modify: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] **Step 1: Write the failing test**

在 System Admin 组件测试中渲染含 `created_at` 的 DataTable，断言页面出现上海中文时间且不出现 ISO 原值。

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix admin-web test -- --run system-admin/src/system-admin.test.tsx`
Expected: FAIL，当前 DataTable 原样输出 ISO 值。

- [ ] **Step 3: Write minimal implementation**

让 `renderCell(field, value)` 在字段名命中时间规则时调用 `formatShanghaiDateTime(value)`，其余字段保持原渲染逻辑；租户与店铺列表已有 `renderCell` 调用，因此自动获得相同格式。

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix admin-web test -- --run system-admin/src/system-admin.test.tsx`
Expected: PASS。

- [ ] **Step 5: Commit**

Run: `git add admin-web/shared/data.tsx admin-web/system-admin/src/system-admin.test.tsx && git commit -m "feat: format admin table timestamps in Shanghai time"`

### Task 3: 覆盖自定义页面时间显示

**Files:**
- Modify: `admin-web/system-admin/src/pages/DashboardPage.tsx`
- Modify: `admin-web/system-admin/src/pages/HealthPage.tsx`
- Modify: `admin-web/system-admin/src/pages/LlmGovernancePage.tsx`
- Modify: `admin-web/system-admin/src/pages/ReleasesPage.tsx`
- Modify: `admin-web/shared/trace-replay.tsx`
- Modify: `admin-web/customer-admin/src/App.tsx`
- Modify: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] **Step 1: Write the failing tests**

补充 Dashboard、Health、LLM、Release、trace replay 与 Customer Admin 会话时间断言，覆盖跨日上海时间、空值回退和 ISO 原值不外露。

- [ ] **Step 2: Run focused tests to verify they fail**

Run: `npm --prefix admin-web test -- --run system-admin/src/system-admin.test.tsx shared/trace-node-presentation.test.ts customer-admin/src/simulation-workflow.test.ts`
Expected: FAIL，现有自定义页面仍直接输出 ISO 或浏览器本地时区。

- [ ] **Step 3: Write minimal implementation**

所有用户可见自定义时间改为调用 `formatShanghaiDateTime()`；不得修改 API payload、原始 JSON、`toISOString()` 筛选参数或 `datetime-local` 值。

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `npm --prefix admin-web test -- --run system-admin/src/system-admin.test.tsx shared/trace-node-presentation.test.ts customer-admin/src/simulation-workflow.test.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

Run: `git add admin-web && git commit -m "feat: standardize visible admin timestamps"`

### Task 4: 增加静态门禁并同步设计文档

**Files:**
- Modify: `admin-web/scripts/assert-ui-regressions.mjs`
- Modify: `docs/system-admin-design.md`
- Modify: `docs/customer-admin-design.md`
- Modify: `docs/development-handoff.md`

- [ ] **Step 1: Write the failing guard**

新增静态检查：Admin 生产源码不得直接使用 `.toLocaleString(`，`Intl.DateTimeFormat` 只能存在于共享时间模块。

- [ ] **Step 2: Run guard to verify current violations are detected**

Run: `node admin-web/scripts/assert-ui-regressions.mjs`
Expected: FAIL，并列出尚未迁移的直接本地化调用（若 Task 3 已清除，则先用现有源码快照验证规则单测，再保留门禁）。

- [ ] **Step 3: Update documentation and handoff**

记录所有 Admin 用户可见时间固定上海时区中文格式；明确 API、数据库、原始技术数据与筛选协议仍使用 UTC/ISO。

- [ ] **Step 4: Run guard and tests**

Run: `node admin-web/scripts/assert-ui-regressions.mjs && npm --prefix admin-web test`
Expected: PASS。

- [ ] **Step 5: Commit**

Run: `git add admin-web/scripts/assert-ui-regressions.mjs docs && git commit -m "docs: define Admin Shanghai time standard"`

### Task 5: 完整验证、发布与线上复验

**Files:**
- Verify only; no expected production-code files.

- [ ] **Step 1: Install dependencies and run full verification**

Run: `npm --prefix admin-web install && npm --prefix admin-web test && npm --prefix admin-web run build`
Expected: all tests and both Admin builds PASS。

- [ ] **Step 2: Review diff and run secret scan**

Run: `git diff origin/main...HEAD --check`，并按仓库规则扫描暂存差异中的密钥模式。
Expected: 无格式错误、无密钥、无范围外修改。

- [ ] **Step 3: Push and open a ready PR**

推送 `codex/admin-shanghai-time`，创建非草稿 PR，等待 required checks 全部通过。

- [ ] **Step 4: Merge and deploy**

合并 PR，等待 `Publish Images` 完成，再等待 `Deploy Dev GitOps` 完成并确认 K8s rollout healthy。

- [ ] **Step 5: Verify live Admin hosts**

验证 API、Customer Admin、System Admin health；在 System Admin 租户列表和至少一个其他时间页面确认中文上海时间、不再出现 `T`/`Z` ISO 展示，并确认两个站点仍只调用各自的 `/auth/me`。
