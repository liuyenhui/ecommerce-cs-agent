# Admin Web UI/UX 审计与整改拆分

审计日期：2026-06-19
审计对象：

- Customer Admin：`https://admin.ecommerce-cs-agent-dev.fcihome.com`
- System Admin：`https://system-admin.ecommerce-cs-agent-dev.fcihome.com`

## Overall Assessment

两个后台已经完成站点和登录边界拆分，基础布局可用，视觉方向接近企业控制台：左侧深色导航、浅色内容区、低圆角、轻边框和数据表格为主。当前主要问题不在“是否能用”，而在上线后的专业度、移动端可用性和敏感信息呈现：系统后台把当前系统用户对象以 raw JSON 直接展示在右侧摘要中，移动端导航占据首屏过多空间，表格在窄屏下丢失字段标签，登录页仍预填测试账号。建议先处理 P0/P1，再做视觉细节和状态反馈打磨。

## Evidence

- Inspection source：Chrome live page inspection；使用 `.env` 中已有后台凭据登录，未输出密码、Cookie、Secret 或哈希。
- Viewports checked：
  - Desktop：1440 x 1000
  - Mobile emulation：390 x 844
- Logged-in evidence：
  - Customer Admin 登录后可见 `Customer Admin`、`首页概览`、`客户上下文`、`维护商品`。
  - System Admin 登录后可见 `System Admin`、`系统首页`、`运行摘要`、`定位决策`。
- Screenshot evidence：本次审计截图保存在本机临时目录 `/tmp/ecommerce-cs-agent-ui-audit/`，不进入 Git。
- Notes：
  - Chrome 控制台出现的 `blob:` / ObjectMultiplex / addListener 报错疑似浏览器扩展注入，不作为应用缺陷结论；若后续无扩展环境复现，再纳入缺陷。
  - 页面右下角粉色浮层来自浏览器扩展环境，不作为应用 UI 一部分。

## Scorecard

| Dimension | Score | Notes |
|---|---:|---|
| Information architecture | 6/10 | 客户/系统后台分区清楚；系统后台导航分组合理。但移动端首屏先看到完整导航，主任务入口被推后；系统右侧摘要混入 raw user object。 |
| Visual hierarchy | 6/10 | 头部、指标卡、表格层级基本成立；但操作按钮、用户徽标和刷新按钮权重接近，系统页右侧 JSON 视觉噪声过强。 |
| Interaction design | 5/10 | 登录、刷新、筛选、导航可操作；但登录页预填测试值，空态缺下一步，系统筛选在移动端过长，部分操作缺 loading/disabled 语义。 |
| Responsive behavior | 5/10 | 无横向溢出，基础堆叠成功；但移动端导航占用过高、表格字段标签丢失、系统上下文 JSON 在窄屏很难读。 |
| Accessibility | 6/10 | 原生 label 和 button 基础可用；但移动表格隐藏表头后未提供字段标签，状态过度依赖颜色，焦点态不够明显。 |
| Modern Web quality | 5/10 | 风格克制，未过度装饰；但 raw JSON、默认测试账号、过长移动首屏让页面仍像工程样机。 |
| Engineering feasibility | 8/10 | 前端集中在 `admin-web/src/main.tsx` 和 `admin-web/src/styles.css`，整改可按组件小步完成，风险主要是不要触碰 API / session 边界。 |

## Key Findings

### P0 Must Fix

- System Admin 右侧 `运行摘要` 直接展示当前系统用户 raw JSON，包含系统用户 ID、email、role 等字段。影响：高权限后台把对象结构当作 UI，会降低专业可信度，并增加不必要的身份信息暴露。Evidence：System desktop 和 mobile 登录后右侧/底部 `RecordSummary` 显示完整 JSON。Fix direction：改为 allowlist 用户摘要组件，只显示 display name、role、状态和必要能力摘要；详情 JSON 仅在调试抽屉中按字段脱敏展示。

### P1 High Priority

- 移动端导航占据首屏过多高度。影响：390px 宽度下，用户先看到完整深色导航和分组，核心 dashboard 被推到第二屏；系统后台尤其明显。Evidence：customer mobile、system mobile 截图首屏顶部为整块导航。Fix direction：移动端改为 compact top app bar + 可展开导航抽屉或横向 tab，默认只露出品牌、当前页面和菜单按钮。
- 移动端表格隐藏表头后没有字段标签。影响：`org-001 / org-001 / active`、`org-a / store-a-1 / blocked / -` 在移动端无法快速判断字段含义。Evidence：customer mobile 组织/店铺表、system mobile 上线阻断队列。Fix direction：移动端把表格行渲染成 labeled record cards，每个 cell 显示 `字段名 + 值`，保留状态 badge。
- 登录页预填测试邮箱和组织 ID。影响：dev/live host 给用户“测试环境未收口”的观感，也可能误导自动化和真实用户；系统后台入口尤其不应预填固定账号。Evidence：登录前 DOM 显示 customer email、system email 和 `org-001` 默认值。Fix direction：登录表单默认空值；如需要演示预填，使用明确的 dev-only flag 或 query opt-in，且不在 live dev host 默认开启。
- 系统筛选区在移动端变成 4 个输入 + 查询按钮的长块，缺少收起/摘要。影响：核心系统指标和阻断队列被筛选栏推后，重复访问成本高。Evidence：system mobile 截图中筛选区域占用一整屏上部。Fix direction：移动端默认折叠高级筛选，只显示“筛选”按钮和已应用条件摘要；展开后再显示字段。

### P2 Polish

- 空态只显示 `暂无记录`，缺少说明和下一步。影响：用户不知道是未配置、筛选无结果、权限受限还是系统正常无数据。Evidence：系统首页 `最近消息决策`。Fix direction：按场景显示标题、简短原因和下一步行动，例如“填写组织与店铺后查询决策”。
- 指标卡和右侧上下文重复信息偏多。影响：桌面宽屏中 customer dashboard 大量空白，右侧上下文重复指标卡信息；system dashboard 同时显示 metric grid 和 summary。Fix direction：保留右侧为“当前上下文/当前账号/最近活动”，避免重复计数。
- 操作权重不够清晰。影响：`刷新`、用户 badge、退出、主操作按钮视觉权重接近；重复刷新按钮也容易让用户不知道刷新的是会话还是数据。Fix direction：把会话刷新降级为图标/菜单操作，把页面数据刷新留在内容区；主操作保持唯一蓝色。
- 状态表达仍偏工程化。影响：`blocked`、字段名 `organization_id`、`store_id` 对业务用户不友好。Fix direction：在 UI 层使用中文标签和简短解释，同时保留 raw id 作为次级 monospace 文本。

## Page-Level Remediation

### System Admin 运行摘要与用户信息

- Problem：`RecordSummary` 直接把 `session.user` 作为 JSON 放在 `ContextPanel` 中。
- Recommendation：新增 `UserSummary` / `SystemUserSummary`，只显示姓名、角色、状态、能力数量或最后登录时间；隐藏 email 或仅按策略脱敏；raw JSON 不出现在 dashboard。
- Acceptance criteria：
  - System Admin desktop/mobile 不再显示 `{ "id": ... }` 这类 raw JSON。
  - 页面不展示完整 email；如必须展示，使用脱敏格式或仅在用户明确打开详情时展示。
  - `ContextPanel` 高度在 desktop 不超过首屏主要内容高度，在 mobile 不出现长 JSON 滚动块。
- Needs product/brand confirmation：No.

### Mobile Shell Navigation

- Problem：小屏下 `.rail` 变为完整顶部块，系统后台首屏被导航占用。
- Recommendation：`max-width: 900px` 下改为 compact header：品牌 + 当前 workspace/page + 菜单按钮；导航放入可展开 panel 或 drawer；展开态可关闭并支持 Escape/点击遮罩。
- Acceptance criteria：
  - 390px 宽度首屏能看到页面标题、主要筛选或指标卡，不被完整导航吞掉。
  - Customer / System 不出现对方后台入口。
  - 所有导航项仍可键盘聚焦和点击。
- Needs product/brand confirmation：No.

### Mobile Tables

- Problem：`thead { display: none }` 后每个 `td` block 化，但没有字段标签。
- Recommendation：在 `DataTable` / `ListPanel` 中为每个 cell 写入 `data-label`，移动端用 `td::before { content: attr(data-label) }` 或直接渲染 labeled row；状态值保持 badge。
- Acceptance criteria：
  - 移动端每条记录显示字段名和值，例如 `组织 ID org-001`、`店铺 ID store-001`、`状态 blocked`。
  - 桌面表格仍保留原有表头和紧凑密度。
  - 空表格显示结构化空态，不只显示 `暂无记录`。
- Needs product/brand confirmation：No.

### Login Forms

- Problem：登录页默认带 `admin@example.test`、`system-admin@example.test`、`org-001`。
- Recommendation：默认清空 email/password；customer organization 可使用 placeholder 或 last-used non-sensitive value，但不预填测试组织；错误态显示在 form 内，toast 仅作辅助。
- Acceptance criteria：
  - 未登录打开两个 host 时，邮箱和密码为空。
  - 表单包含 required validation、loading disabled、错误 message，不改变 API path 和 Cookie/session 边界。
  - dev-only 演示预填必须显式 opt-in，不能成为 live 默认行为。
- Needs product/brand confirmation：No.

### Empty / Loading / Status Feedback

- Problem：加载、空态、错误和状态 badge 缺少足够上下文。
- Recommendation：抽象 `EmptyState`、`InlineError`、`LoadingBlock` 和 `StatusBadge`，覆盖 dashboard、表格、操作面板和筛选结果。
- Acceptance criteria：
  - 加载数据时有明确 busy 状态，不误显示旧值或空表。
  - `blocked`、`active`、`pending` 等状态在 UI 层显示中文标签和颜色，颜色不是唯一信息。
  - 空态提供下一步，例如“填写组织 ID 和店铺 ID 后查询决策”。
- Needs product/brand confirmation：No.

## Engineering Task Breakdown

### Task 1: Sanitize Context Panels and User Summary

- Goal：去掉系统后台 raw JSON，建立安全、可扫描的上下文摘要。
- Scope：System Admin `ContextPanel`、`RecordSummary` 使用点、用户摘要和字段脱敏。
- Suggested files/components：`admin-web/src/main.tsx`、`admin-web/src/styles.css`。
- Implementation notes：新增 allowlist summary 组件；`RecordSummary` 保留给抽屉或操作结果，但不要用于系统用户对象；避免显示完整 email。
- Acceptance criteria：System desktop/mobile 不出现 raw JSON；用户摘要保持可读；Customer context 不退化。
- Verification：`npm --prefix admin-web test`、`npm --prefix admin-web run build`、Chrome desktop/mobile 截图检查。
- Risk：低；主要是 UI 呈现，不改 API。
- Needs product confirmation：No.

### Task 2: Mobile Admin Shell Navigation

- Goal：让 390px 移动视口下首屏优先展示当前任务，而不是完整导航。
- Scope：`appShell`、`.rail`、`Navigation`、移动端导航展开/收起状态。
- Suggested files/components：`admin-web/src/main.tsx`、`admin-web/src/styles.css`。
- Implementation notes：用按钮打开移动导航 panel；desktop 保持现有 rail；不要加入后台切换入口；保留 aria label 和 focus state。
- Acceptance criteria：移动首屏能看到页面标题和至少一组核心指标/筛选；导航可打开关闭；无横向滚动。
- Verification：`npm --prefix admin-web test`、`npm --prefix admin-web run build`、390x844 customer/system Chrome 检查。
- Risk：中；需要谨慎避免破坏 desktop rail。
- Needs product confirmation：No.

### Task 3: Responsive Data Tables and Empty States

- Goal：移动端表格行可读，空态能说明原因和下一步。
- Scope：`DataTable`、`ListPanel`、`AuditTable`、`EmptyState`、状态 badge。
- Suggested files/components：`admin-web/src/main.tsx`、`admin-web/src/styles.css`。
- Implementation notes：给 fields 做中文 label map；移动端渲染字段名；桌面保留表格密度；状态显示中文 + 原始状态可选作为 title。
- Acceptance criteria：移动端每个值有字段名；空表有说明；状态不只靠颜色。
- Verification：`npm --prefix admin-web test`、`npm --prefix admin-web run build`、customer/system mobile 截图检查。
- Risk：中；表格组件共用面广，但逻辑可局部。
- Needs product confirmation：No.

### Task 4: Login Form Hardening and Interaction Feedback

- Goal：登录页去除默认测试值，增强错误、加载和可访问性反馈。
- Scope：`LoginPanel`、toast/form error、按钮 loading/disabled、placeholder/help text。
- Suggested files/components：`admin-web/src/main.tsx`、`admin-web/src/styles.css`、现有 admin-web tests。
- Implementation notes：默认 email/password 为空；customer org 默认也为空或仅 placeholder；submit 前 required 检查；错误显示在 form 内；保持 `/v1/admin/auth/*` 与 `/v1/system-admin/auth/*` 边界。
- Acceptance criteria：两个 host 未登录时不预填测试账号；错误可见且不只在 toast；登录成功后仍进入对应后台；session Cookie 名和路由守卫不变。
- Verification：`npm --prefix admin-web test`、`npm --prefix admin-web run build`、Chrome 登录 customer/system。
- Risk：中；可能影响自动化登录脚本，需要同步测试用例显式填写 email/org。
- Needs product confirmation：No.

## Codex-Ready Development Prompts

### Prompt: Sanitize Context Panels and User Summary

```text
你在项目 /Users/huiliu/.codex/worktrees/0371/ecommerce-cs-agent 工作。

Goal:
修复 Admin Web 右侧上下文面板的信息呈现：System Admin 不得在 dashboard 直接显示 raw JSON、完整用户对象或完整 email；Customer Admin 保持上下文清晰。

Background:
UI/UX 审计发现 system-admin 登录后右侧“运行摘要”直接渲染 session.user 的 JSON，包含 id、system_user_id、email、roles 等字段。该呈现像调试面板，不适合高权限后台，也增加不必要的信息暴露。

Scope:
- admin-web/src/main.tsx
- admin-web/src/styles.css
- 仅改前端呈现，不改 API、Cookie、session、路由守卫或鉴权边界。

Constraints:
1. Preserve existing business logic.
2. Do not do unrelated refactors.
3. Follow AGENTS.md: 客户后台和系统后台职责、导航、session 边界不得混淆。
4. Desktop and mobile both need clean presentation.
5. 不输出、提交或截图真实密码、Cookie、Secret。

Implementation guidance:
- 新增 UserSummary/SystemUserSummary 之类 allowlist 组件，只显示 display_name/name、role/roles、status、必要的 capabilities count 或 last_login_at。
- 不在 dashboard 直接使用 RecordSummary 渲染 session.user。
- 如需要显示 email，默认脱敏；更推荐不在摘要展示。
- RecordSummary 可继续用于操作结果、抽屉详情或调试性质内容，但不要用于系统用户摘要。
- 保持 Customer Admin 的“客户上下文”指标可读。

Acceptance criteria:
- system-admin desktop/mobile 登录后不出现以 { 开头的 raw JSON 用户对象。
- system-admin dashboard 不显示完整 email。
- Customer Admin 的组织/店铺/成员/审计摘要仍正常。
- 无横向滚动；移动端摘要不出现长 JSON 块。

Verification:
- npm --prefix admin-web test
- npm --prefix admin-web run build
- Chrome 登录 https://admin.ecommerce-cs-agent-dev.fcihome.com 和 https://system-admin.ecommerce-cs-agent-dev.fcihome.com，检查 desktop 与 390px mobile。

Return:
- Files changed
- Visual/interaction changes
- Verification results
- Remaining risks or decisions needed
```

### Prompt: Mobile Admin Shell Navigation

```text
你在项目 /Users/huiliu/.codex/worktrees/0371/ecommerce-cs-agent 工作。

Goal:
优化 Admin Web 移动端壳层导航，让 390px 视口下首屏优先展示当前页面内容，而不是完整深色导航。

Background:
UI/UX 审计发现 customer/system 移动端把 desktop rail 直接堆到顶部，完整导航占据首屏大量空间；system-admin 更明显，核心筛选和指标被推后。

Scope:
- admin-web/src/main.tsx
- admin-web/src/styles.css
- 只改 shell / navigation / responsive CSS，不改后台切换逻辑。

Constraints:
1. Preserve existing business logic.
2. Do not add customer/system switcher.
3. Customer host 不能出现系统后台入口；system host 不能出现客户后台入口。
4. Desktop rail 保持现有企业后台密度和布局。
5. Cover desktop and mobile behavior.

Implementation guidance:
- 在 <=900px 或 <=560px 下，把 .rail 改为 compact mobile header：品牌、当前后台/当前页、菜单按钮。
- 导航项放入可展开 panel/drawer；默认收起。
- 展开导航后点击任一 tab 自动关闭；支持 aria-expanded、aria-controls、aria-label。
- 保持 nav group 文案，但移动端不要占满首屏。
- 给 focus-visible 状态补足可见焦点。

Acceptance criteria:
- 390x844 下 customer/system 首屏能看到页面标题和核心内容。
- 移动端无横向滚动。
- 桌面 1440px 下仍是左侧 rail。
- 导航打开、关闭、切换 tab 都可用。

Verification:
- npm --prefix admin-web test
- npm --prefix admin-web run build
- Chrome 检查 customer/system desktop 1440x1000 和 mobile 390x844。

Return:
- Files changed
- Visual/interaction changes
- Verification results
- Remaining risks or decisions needed
```

### Prompt: Responsive Data Tables and Empty States

```text
你在项目 /Users/huiliu/.codex/worktrees/0371/ecommerce-cs-agent 工作。

Goal:
修复 Admin Web 移动端表格可读性，并补齐空态/状态表达。

Background:
UI/UX 审计发现移动端隐藏 thead 后，表格 cell 直接堆叠，用户看到 org-001/org-001/active 或 org-a/store-a-1/blocked/- 时不知道字段含义。空态目前只有“暂无记录”，缺少原因和下一步。

Scope:
- admin-web/src/main.tsx
- admin-web/src/styles.css
- 影响 DataTable、ListPanel、AuditTable、StatusBadge/empty state 等前端呈现。

Constraints:
1. Preserve existing business logic and API field names.
2. Desktop table must remain dense and scannable.
3. Mobile must show field labels and values.
4. Status must not rely on color alone.
5. Do not change backend contracts.

Implementation guidance:
- 为 fields 增加 UI label map，例如 organization_id -> 组织 ID、store_id -> 店铺 ID、status -> 状态。
- 在 td 上写 data-label，移动端用 CSS before 显示字段名，或渲染 mobile record cards。
- Status badge 显示中文状态 + 可选 title 保留原始值。
- EmptyState 组件支持 title、description、action；用于最近消息决策、空表格、筛选无结果。
- 不要把 table 改成营销式卡片；保持企业后台密度。

Acceptance criteria:
- 390px mobile 下每个表格值旁有字段名。
- Desktop table 表头、列宽、密度不退化。
- Empty state 能解释“没有数据”和下一步。
- blocked/active 等状态同时有文字和颜色。

Verification:
- npm --prefix admin-web test
- npm --prefix admin-web run build
- Chrome mobile 检查 Customer 组织/店铺表、System 上线阻断队列、最近消息决策空态。

Return:
- Files changed
- Visual/interaction changes
- Verification results
- Remaining risks or decisions needed
```

### Prompt: Login Form Hardening and Interaction Feedback

```text
你在项目 /Users/huiliu/.codex/worktrees/0371/ecommerce-cs-agent 工作。

Goal:
加固 Customer/System Admin 登录页：去掉默认测试账号预填，补齐表单校验、错误反馈和 loading 状态。

Background:
UI/UX 审计发现两个 live dev host 的登录表单默认预填 admin@example.test / system-admin@example.test，customer 还预填 org-001。这让页面显得像工程样机，也可能误导真实用户或自动化。

Scope:
- admin-web/src/main.tsx 的 LoginPanel
- admin-web/src/styles.css 的 login/error/loading/focus 样式
- 如已有测试，更新显式填写 email/password/org。

Constraints:
1. Preserve API endpoints:
   - customer login only uses /v1/admin/auth/login and /v1/admin/auth/me
   - system login only uses /v1/system-admin/auth/login and /v1/system-admin/auth/me
2. Preserve Cookie/session boundary.
3. Do not log or render passwords, Cookie, Authorization, Secret.
4. Do not add SSO or new auth features.

Implementation guidance:
- email/password 默认空字符串。
- customer organization_id 默认空或只用 placeholder；如 dev demo 需要预填，必须显式 opt-in，例如 Vite env flag 或 query 参数，默认关闭。
- 提交前做 required validation，错误显示在 form 内；toast 可保留但不作为唯一错误反馈。
- loading 时按钮 disabled，显示 spinner 和稳定按钮宽度。
- 补充 autocomplete、aria-invalid、aria-describedby。

Acceptance criteria:
- 未登录打开两个 host 时，不显示默认测试邮箱。
- 空字段提交时显示表单内错误，不发起无效请求。
- 填入正确 .env 凭据后，Chrome 可登录 customer/system 对应后台。
- 客户后台不出现系统入口，系统后台不出现客户入口。

Verification:
- npm --prefix admin-web test
- npm --prefix admin-web run build
- Chrome 登录 customer/system live host。

Return:
- Files changed
- Visual/interaction changes
- Verification results
- Remaining risks or decisions needed
```
