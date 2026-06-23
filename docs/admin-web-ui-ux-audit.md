# Admin Web UI/UX 审计与整改计划

更新时间：`2026-06-18`

本文面向客户 Admin Web 与系统 Admin Web 的第一版 UI/UX 整改。审计目标是保持当前企业控制台方向，优先修复会影响登录、后台边界感、移动端可用性、可访问性和专业度的问题，不做与业务逻辑无关的重设计。

## 登录与鉴权信息

| 后台 | 访问地址 | 登录接口 | 会话 Cookie | 账号来源 |
| --- | --- | --- | --- | --- |
| 客户 Admin | `https://admin.ecommerce-cs-agent-dev.fcihome.com` | `POST /v1/admin/auth/login` | `agent_admin_session` | `ADMIN_INITIAL_EMAIL`、`ADMIN_INITIAL_PASSWORD_HASH` |
| 系统 Admin | `https://system-admin.ecommerce-cs-agent-dev.fcihome.com` | `POST /v1/system-admin/auth/login` | `agent_system_admin_session` | `SYSTEM_ADMIN_INITIAL_EMAIL`、`SYSTEM_ADMIN_INITIAL_PASSWORD_HASH`，未设置时按配置回退到客户 Admin 初始账号 |

安全说明：

- 本文不记录真实密码、Cookie 值、Secret 明文、kubeconfig、Authorization header 或生产数据。
- 当前 live 登录口令必须从批准的 Secret 渠道获取；不要从聊天记录、文档或代码提交中传递。
- 仓库代码和测试中存在本地 / 测试默认账号占位值，不能把这些占位值当成线上凭据。
- 当前 live 未登录页会预填测试邮箱和客户租户 ID，这是 UI/UX 与安全信任问题，应作为高优先级整改项移除。

## Overall Assessment

两个后台的站点边界、请求路径和基础企业控制台视觉方向已经建立：Customer host 只请求 `/v1/admin/auth/me`，System host 只请求 `/v1/system-admin/auth/me`。主要问题集中在未登录态：页面把完整后台导航和刷新操作暴露在登录前，移动端导航占据首屏，登录表单被推到折线以下，且 live 表单预填测试邮箱 / 租户 ID，降低专业感和安全信任。客户 Admin 当前也没有呈现预期的公开宣传页，首次访问更像内部后台登录壳。建议先修复登录前体验和移动端结构，再打磨后台 shell 的密度、状态和可访问性。

## Evidence

- Inspection source: live page + Playwright/Chrome 截图 + DOM 指标 + 代码阅读。
- Viewports checked:
  - Desktop: `1440x900`
  - Mobile: `390x844`
- Live URLs:
  - `https://admin.ecommerce-cs-agent-dev.fcihome.com/`
  - `https://system-admin.ecommerce-cs-agent-dev.fcihome.com/`
- Auth boundary evidence:
  - Customer host network request: `/v1/admin/auth/me`
  - System host network request: `/v1/system-admin/auth/me`
- Not inspected live:
  - 登录后页面。真实 live 口令未读取，也未写入文档。
  - 登录错误态。错误态结论来自代码与可见表单结构推断。

## Scorecard

| Dimension | Score | Notes |
|---|---:|---|
| Information architecture | 6/10 | 后台拆站清楚，但未登录态展示完整后台导航，客户站点缺少公开宣传首页。 |
| Visual hierarchy | 6/10 | 控制台基调克制，但登录前导航、标题、刷新按钮和表单竞争注意力。 |
| Interaction design | 5/10 | 登录前出现刷新和后台 tab；表单预填测试值；错误、加载、禁用状态不够成体系。 |
| Responsive behavior | 5/10 | 无横向溢出，但移动端 rail 占用 275-429px，高优先级登录任务被下推。 |
| Accessibility | 6/10 | 基本 label 存在；按钮 / 输入高度低于移动端 44px 建议，焦点和错误反馈需加强。 |
| Modern Web quality | 6/10 | 有企业 console 基础，但未登录页仍像工程内测页面，缺少产品可信度和完成度。 |
| Engineering feasibility | 8/10 | 多数问题可在 `admin-web/src/main.tsx` 和 `admin-web/src/styles.css` 内局部修复。 |

## Key Findings

### P0 Must Fix

当前没有发现阻断登录页加载或造成横向溢出的 P0 UI 问题。

### P1 High Priority

- 客户 Admin 根路径没有公开宣传页。影响：客户首次访问无法理解产品价值和登录入口层级。Evidence：desktop/mobile live 页面直接展示内部 console shell + 登录卡片。Fix direction：在 customer host 未登录 `/` 提供 Notion-led 产品介绍与 CTA，`/login` 承载客户登录，`/admin` 承载受保护后台。
- 未登录态展示完整后台导航。影响：用户尚未登录却看到功能菜单，削弱安全边界感，也把登录主任务挤到次级位置。Evidence：Customer/System desktop 和 mobile 均显示 rail + tabs。Fix direction：未登录时只显示精简品牌、站点类型、登录卡片和必要帮助链接；登录后再渲染后台导航。
- 移动端登录被导航下推。影响：system mobile 中登录表单顶部约在 `808px`，首屏主要被导航占用，核心任务不可立即完成。Evidence：Playwright 指标显示 system mobile rail 高 `429px`，customer mobile rail 高 `275px`。Fix direction：移动端未登录隐藏 rail，登录卡片进入首屏；登录后使用可折叠 drawer 或顶部栏导航。
- live 登录表单预填测试邮箱和租户 ID。影响：显得像测试环境泄露，用户也可能误以为这些是可用凭据。Evidence：Customer 显示 `admin@example.test` 和 `org-001`，System 显示测试邮箱。Fix direction：线上构建不预填账号；用 placeholder / helper text 展示输入格式。
- Customer 与 System 未登录页面区分度不足。影响：两个后台都像同一个 app 的文案替换版，系统后台的高权限风险感不足。Evidence：布局、颜色、登录卡片完全一致。Fix direction：保持同一设计系统，但用不同的页面标题、辅助说明、安全提示和高权限标识区分。

### P2 Polish

- 按钮和输入高度偏小。影响：移动端点击容错不足。Evidence：按钮高约 `38px`，输入高约 `32px`。Fix direction：移动端表单控件最小高度提升到 `44px`，桌面保持紧凑但不低于 `36px`。
- 登录前刷新按钮语义不清。影响：未登录时“刷新”会话没有明确用户价值。Evidence：top bar 始终显示刷新。Fix direction：未登录隐藏刷新；登录后改为图标按钮并保留可访问 label。
- 登录卡片缺少上下文与错误恢复区域。影响：失败时用户只依赖 toast，不能清楚知道下一步。Evidence：代码使用 toast 反馈，卡片内无固定错误区。Fix direction：在表单内显示错误摘要、字段级提示和提交中状态。
- 视觉密度在桌面首屏过空。影响：桌面登录表单孤立，页面缺少可建立信任的产品信息。Evidence：desktop 登录卡片周围大面积空白。Fix direction：客户登录前增加产品证明 / 能力摘要；系统登录前增加安全提示 / 环境标识。

## Page-Level Remediation

### Customer Public Entry

- Problem: `admin` host 未登录根路径直接呈现内部后台 shell，未体现公开宣传页职责。
- Recommendation: 增加 customer public landing。首屏应包含产品名称、AI Agent 价值陈述、能力模块、信任证明和黑色主 CTA；CTA 进入 `/login`。不要把登录表单塞进营销卡片。
- Acceptance criteria:
  - `GET /` 未登录显示公开宣传页，不展示后台 nav。
  - `GET /login` 显示客户登录表单。
  - `GET /admin` 未登录进入客户登录页或登录状态。
  - mobile 首屏能看到主 CTA 和下一段内容提示。
- Needs product/brand confirmation: yes，需要确认公开页文案与信任证明内容。

### Login Surfaces

- Problem: 两个登录页共享同一视觉结构且预填测试值，缺少站点边界提示。
- Recommendation: 提取 `LoginLayout` 与 `LoginPanel`，按 workspace 注入标题、说明、安全提示、字段集。移除 live 默认值；本地开发可通过显式 dev flag 才预填。
- Acceptance criteria:
  - live 表单初始值为空，placeholder 不含真实或测试凭据。
  - customer 登录包含租户 ID 字段；system 登录不包含租户 ID。
  - customer 页面不出现“系统后台”入口；system 页面不出现“客户后台”入口。
  - 登录失败在表单内显示错误摘要，toast 仅作辅助反馈。
- Needs product/brand confirmation: no。

### Mobile Navigation

- Problem: 移动端未登录先渲染完整 rail，核心登录任务被下推。
- Recommendation: 未登录移动端隐藏 rail；登录后使用 top app bar + drawer 或 segmented page nav。系统后台可按 group 折叠菜单。
- Acceptance criteria:
  - `390x844` customer/system 登录页无需滚动即可看到主要表单字段和提交按钮。
  - 登录后移动端导航不造成横向溢出，tap target 不小于 `44px`。
  - System Admin 六个 tab 在移动端不会形成 400px 以上的固定首屏占用。
- Needs product/brand confirmation: no。

### Admin Shell Visual Baseline

- Problem: 当前 shell 有 IBM/Carbon 式骨架，但控件状态、空状态和错误状态不足，专业完成度偏工程原型。
- Recommendation: 建立项目级 token 和状态组件：empty state、inline alert、loading skeleton、field error、toolbar density。保持低阴影、细分隔线、表格优先。
- Acceptance criteria:
  - 主要列表 / 表单 / 审计页具备 empty、loading、error、success 状态。
  - 按钮区分 primary / secondary / destructive / icon-only，并有 accessible label。
  - 颜色不依赖单一蓝色表达所有状态。
- Needs product/brand confirmation: no。

## Engineering Task Breakdown

### Task 1: Customer Public Landing 与登录路由分离

- Goal: 让 customer host 符合公开宣传页 + 客户登录 + 受保护后台的三段式入口。
- Scope: customer host 未登录 `/`、`/login`、`/admin`。
- Suggested files/components: `admin-web/src/main.tsx`、`admin-web/src/styles.css`、必要时更新 `docs/customer-admin-design.md`。
- Implementation notes: 不引入新业务 API；用前端 route state 或 `window.location.pathname` 区分 public/login/admin；保持 host-based workspace detection。
- Acceptance criteria: 未登录根路径不显示后台 nav；客户后台页面不出现系统后台入口；mobile 首屏可看到 CTA。
- Verification: `npm --prefix admin-web test`、`npm --prefix admin-web run build`、Playwright desktop/mobile screenshot。
- Risk: 登录跳转路径可能影响现有 `/` 直达后台习惯。
- Needs product confirmation: yes，公开页文案。

### Task 2: 独立登录页与安全态表单

- Goal: Customer/System 登录页更专业、边界更清晰，并移除 live 预填测试数据。
- Scope: 登录表单、错误反馈、提交态、字段 helper text。
- Suggested files/components: `LoginPanel`、新增 `LoginShell` / `AuthMessage`，`styles.css`。
- Implementation notes: 初始值默认为空；如需本地预填，用 `import.meta.env.DEV` 或显式环境变量控制；错误显示在表单内。
- Acceptance criteria: live 不预填测试邮箱和租户 ID；登录失败不只依赖 toast；system 登录页不出现客户租户字段。
- Verification: TypeScript build；手动输入错误凭据检查 inline error；检查 DOM 中无默认测试值。
- Risk: 测试用例若依赖预填值需调整。
- Needs product confirmation: no。

### Task 3: Mobile Admin Shell 与未登录导航重构

- Goal: 修复移动端首屏导航过高和登录任务下沉。
- Scope: `.appShell`、`.rail`、`.topBar`、未登录和登录后移动端导航。
- Suggested files/components: `Navigation`、`TopBar`、`styles.css`。
- Implementation notes: 未登录隐藏 rail；登录后 mobile 使用 drawer / collapsible nav；桌面保持左 rail。
- Acceptance criteria: `390x844` 两个登录页表单提交按钮首屏可见；无横向溢出；tap target >= `44px`。
- Verification: Playwright `390x844` screenshot + DOM scrollWidth/clientWidth 检查。
- Risk: 登录后移动端导航交互需覆盖键盘和 aria label。
- Needs product confirmation: no。

### Task 4: Admin 状态组件与可访问性补强

- Goal: 提升后台 shell 的完成度、可访问性和状态反馈。
- Scope: empty/loading/error/success/disabled/focus 状态，按钮和表单控件尺寸。
- Suggested files/components: `styles.css`、共享小组件、现有 workspace panels。
- Implementation notes: 不改 API contract；优先抽 `InlineAlert`、`EmptyState`、`LoadingBlock`；补 `aria-label`、`aria-current`、焦点样式。
- Acceptance criteria: 键盘可达；focus ring 清晰；移动端控件最小高度达标；错误信息不只用颜色表达。
- Verification: keyboard tab pass、desktop/mobile screenshot、TypeScript build。
- Risk: 样式改动面较广，需要避免影响数据表格密度。
- Needs product confirmation: no。

## Codex-Ready Development Prompts

### Prompt: Customer Public Landing 与登录路由分离

```text
You are working in project: /Users/huiliu/Documents/software/ecommerce-cs-agent

Goal:
Implement a proper Customer Admin public entry so admin.ecommerce-cs-agent-dev.fcihome.com has a public landing page, a customer login page, and a protected customer admin shell.

Background:
UI/UX audit found that the current customer host immediately renders the internal admin shell and login card. This conflicts with the project rule that the customer Admin site should include a Notion-led public landing page and should not expose admin navigation before login.

Scope:
- Customer host only: admin.ecommerce-cs-agent-dev.fcihome.com
- Routes or path states: /, /login, /admin
- Suggested files: admin-web/src/main.tsx, admin-web/src/styles.css, docs/customer-admin-design.md if design behavior changes

Constraints:
1. Preserve existing business logic and API contracts.
2. Do not do unrelated refactors.
3. Keep customer/system admin site boundaries isolated.
4. Do not show any system admin entry on customer pages.
5. Do not use external brand assets, copied copywriting, or licensed fonts.

Implementation guidance:
- Keep detectWorkspaceFromLocation host-based behavior.
- Render a customer public landing page at / when unauthenticated.
- Render a customer-specific login page at /login.
- Render the customer admin shell at /admin only after /v1/admin/auth/me succeeds.
- The public page should use black/neutral palette, generous whitespace, concise AI Agent narrative, capability modules, and a black primary CTA.
- Avoid decorative gradient/orb backgrounds and nested cards.

Acceptance criteria:
- Unauthenticated GET / shows public landing, not the admin nav.
- Unauthenticated /login shows customer login only.
- Customer pages contain no system admin nav, tab, switch, or CTA.
- Mobile first viewport shows the primary CTA and a hint of the next section.
- Existing customer auth refresh still only calls /v1/admin/auth/me.

Verification:
- npm --prefix admin-web test
- npm --prefix admin-web run build
- Playwright screenshots for desktop 1440x900 and mobile 390x844
- Confirm no horizontal overflow

Return:
- Files changed
- Visual/interaction changes
- Verification results
- Remaining product copy decisions
```

### Prompt: 独立登录页与安全态表单

```text
You are working in project: /Users/huiliu/Documents/software/ecommerce-cs-agent

Goal:
Make Customer Admin and System Admin login pages professional, clearly separated, and safe for live use.

Background:
UI/UX audit found that live login forms prefill test emails and customer tenant ID, and customer/system login pages look like the same internal shell with text substitutions. This reduces trust and makes the two authorization domains feel less distinct.

Scope:
- LoginPanel and related auth UI in admin-web/src/main.tsx
- Login styles in admin-web/src/styles.css
- Customer login fields: email, password, tenant ID
- System login fields: email, password

Constraints:
1. Preserve /v1/admin/auth/login and /v1/system-admin/auth/login behavior.
2. Do not print or hard-code real credentials.
3. Do not reuse customer session or customer cookie in system admin.
4. Keep customer/system login pages on separate hosts.
5. Avoid broad visual redesign outside auth pages.

Implementation guidance:
- Remove live default field values. Use empty initial values and placeholders/helper text.
- If local development needs prefill, gate it behind import.meta.env.DEV or an explicit non-production flag.
- Add inline error area inside the form for authentication failures.
- Add loading/disabled submit state that preserves layout.
- Add workspace-specific explanatory text: customer manages own tenant data; system manages platform operations and audited cross-tenant access.

Acceptance criteria:
- Live login forms do not prefill test email or tenant ID.
- Customer login does not mention system admin.
- System login does not mention customer admin and does not show tenant ID.
- Auth failure shows a persistent inline message near the form.
- Submit button has loading and disabled states.

Verification:
- npm --prefix admin-web test
- npm --prefix admin-web run build
- Manual or Playwright invalid-login check without printing cookies
- Check rendered DOM text for absence of test default values on live build

Return:
- Files changed
- Visual/interaction changes
- Verification results
- Remaining risks or decisions needed
```

### Prompt: Mobile Admin Shell 与未登录导航重构

```text
You are working in project: /Users/huiliu/Documents/software/ecommerce-cs-agent

Goal:
Fix mobile layout so login is the primary first-screen task and authenticated navigation remains usable without consuming the whole viewport.

Background:
UI/UX audit at 390x844 found that the unauthenticated rail consumes about 275px on Customer Admin and about 429px on System Admin. On system mobile the login form begins near the bottom of the first viewport, making the core task hard to reach.

Scope:
- Mobile CSS for .appShell, .rail, .mainPane, .topBar, .loginSurface, .loginPanel
- Navigation behavior before and after authentication
- Suggested files: admin-web/src/main.tsx, admin-web/src/styles.css

Constraints:
1. Preserve desktop left rail behavior after login.
2. Do not show backend navigation before login.
3. Preserve existing tab keys and API behavior.
4. Do not introduce heavy UI dependencies unless already present.
5. Cover both customer and system admin.

Implementation guidance:
- Hide the rail entirely while unauthenticated.
- On mobile after login, replace the tall rail with a top app bar plus drawer/collapsible nav or compact grouped nav.
- Keep tap targets at least 44px high on mobile.
- Ensure long Chinese labels wrap or truncate predictably.
- Keep scrollWidth equal to clientWidth at 390px.

Acceptance criteria:
- At 390x844, customer and system login pages show the form submit button without requiring scroll.
- No horizontal overflow on mobile.
- System Admin six nav items do not occupy a fixed 400px+ block before content.
- Keyboard focus order remains logical.

Verification:
- npm --prefix admin-web test
- npm --prefix admin-web run build
- Playwright screenshots at 390x844 and 1440x900
- DOM check: documentElement.scrollWidth <= clientWidth

Return:
- Files changed
- Visual/interaction changes
- Verification results
- Remaining risks or decisions needed
```

### Prompt: Admin 状态组件与可访问性补强

```text
You are working in project: /Users/huiliu/Documents/software/ecommerce-cs-agent

Goal:
Improve Admin Web state feedback, accessibility, and control polish without changing business logic.

Background:
UI/UX audit found that the admin shell has a solid enterprise-console base, but form controls are small on mobile, focus/error/loading states are thin, and empty/error states are not standardized. This makes the app feel like an engineering prototype rather than a finished operations tool.

Scope:
- Shared UI states in admin-web/src/main.tsx
- CSS tokens and states in admin-web/src/styles.css
- Buttons, inputs, focus states, inline alerts, empty/loading blocks

Constraints:
1. Preserve API behavior and current data-fetching logic.
2. Keep the IBM/Carbon-like dense enterprise console direction.
3. Do not make logged-in customer Admin Notion-like.
4. Do not add unrelated feature work.
5. Cover desktop and mobile behavior.

Implementation guidance:
- Add or standardize InlineAlert, EmptyState, LoadingBlock, and field error patterns.
- Add visible focus ring styles for buttons, inputs, selects, textarea, and nav buttons.
- Increase mobile tap targets to at least 44px.
- Ensure icon-only or icon+text controls have accessible names.
- Use status colors beyond blue for success/warning/error and do not rely on color alone.

Acceptance criteria:
- Keyboard users can see focus location throughout login and shell controls.
- Error messages are text-visible and not color-only.
- Loading and disabled states do not resize controls.
- Mobile controls meet minimum tap target guidance.

Verification:
- npm --prefix admin-web test
- npm --prefix admin-web run build
- Keyboard tab-through smoke test
- Desktop/mobile screenshots

Return:
- Files changed
- Visual/interaction changes
- Verification results
- Remaining risks or decisions needed
```
