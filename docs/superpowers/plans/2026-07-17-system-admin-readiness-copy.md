# System Admin 未满足上线条件文案 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 System Admin 总览明确区分全部未满足上线条件的店铺总数与仅缺少商品资料的摘要列表，并提供完整原因入口。

**Architecture:** 保持现有服务端统计和接口不变，在 `DashboardPage` 内组合专用摘要面板并通过回调请求 `SystemWorkspace` 切换至 `readiness` 页面。复用 `Metric` 已有的 `title` Tooltip 能力，不扩大共享表格组件接口。

**Tech Stack:** React 18、TypeScript、Vitest、Testing Library、服务端渲染测试

---

### Task 1: 锁定 Dashboard 文案与 Tooltip

**Files:**
- Modify: `admin-web/system-admin/src/system-admin.test.tsx`
- Modify: `admin-web/system-admin/src/pages/DashboardPage.tsx`

- [ ] **Step 1: 写入失败测试**

在 `DashboardPage` 测试中增加断言：

```tsx
expect(html).toContain("未满足上线条件");
expect(html).toContain("缺少商品资料的店铺");
expect(html).toContain("以下店铺因缺少必要配置，暂时无法上线。");
expect(html).toContain("缺少商品资料、缺少价格配置、缺少已审核知识、API 未完成接入");
expect(html).not.toContain("上线阻断摘要");
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `npm --prefix admin-web/system-admin test -- --run src/system-admin.test.tsx`

Expected: FAIL，输出缺少“未满足上线条件”或“缺少商品资料的店铺”。

- [ ] **Step 3: 最小化修改指标文案和摘要面板**

在 `DashboardPage.tsx` 定义 Tooltip 文案并用于指标：

```tsx
const readinessTooltip = "未满足上线条件包括：缺少商品资料、缺少价格配置、缺少已审核知识、API 未完成接入等情况。";

<Metric
  label="未满足上线条件"
  value={String(summary.readiness_blockers)}
  tone="warn"
  title={readinessTooltip}
/>
```

将“优先工作”对应标签改为“未满足上线条件”。将摘要区域放入 `div.dashboardReadinessSummary`，在 `DataTable` 前展示：

```tsx
<p className="panelDescription">以下店铺因缺少必要配置，暂时无法上线。</p>
```

`DataTable` 标题固定为“缺少商品资料的店铺”，无数据时传入：

```tsx
<EmptyState title="暂无缺少商品资料的店铺" description="当前摘要中没有缺少商品资料的店铺。" />
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `npm --prefix admin-web/system-admin test -- --run src/system-admin.test.tsx`

Expected: PASS。

### Task 2: 增加配置完成度跳转

**Files:**
- Modify: `admin-web/system-admin/src/system-admin.test.tsx`
- Modify: `admin-web/system-admin/src/pages/DashboardPage.tsx`
- Modify: `admin-web/system-admin/src/SystemWorkspace.tsx`
- Modify: `admin-web/system-admin/src/App.tsx`

- [ ] **Step 1: 写入失败的交互测试**

使用 Testing Library 渲染成功态 Dashboard，传入导航回调并点击按钮：

```tsx
const onNavigate = vi.fn();
render(<DashboardPage state={dashboardSuccessState} onNavigate={onNavigate} />);
fireEvent.click(screen.getByRole("button", { name: "查看全部未满足上线条件的店铺" }));
expect(onNavigate).toHaveBeenCalledWith("readiness");
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `npm --prefix admin-web/system-admin test -- --run src/system-admin.test.tsx`

Expected: FAIL，按钮不存在或 `DashboardPage` 尚未接受 `onNavigate`。

- [ ] **Step 3: 实现 Dashboard 回调和 Workspace 接线**

修改页面签名并添加按钮：

```tsx
export function DashboardPage({ state, onNavigate }: {
  state: RequestState<DashboardData>;
  onNavigate: (page: "readiness") => void;
}) {
```

```tsx
<button type="button" onClick={() => onNavigate("readiness")}>
  查看全部未满足上线条件的店铺
</button>
```

让 `SystemWorkspace` 接受页面切换回调并传给 Dashboard：

```tsx
export function SystemWorkspace({ activePage, session, setToast, onNavigate }: {
  activePage: SystemPage;
  session?: JsonRecord;
  setToast: (toast: ToastState) => void;
  onNavigate: (page: SystemPage) => void;
}) {
```

```tsx
<DashboardPage state={dashboard} onNavigate={onNavigate} />
```

在 `App.tsx` 将现有 `setActivePage` 传入：

```tsx
<SystemWorkspace
  session={systemSession}
  activePage={activePage}
  setToast={setToast}
  onNavigate={setActivePage}
/>
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `npm --prefix admin-web/system-admin test -- --run src/system-admin.test.tsx`

Expected: PASS。

### Task 3: 样式、边界与整体验证

**Files:**
- Modify: `admin-web/shared/styles/base.css`
- Modify: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] **Step 1: 增加面板说明和底部操作样式**

添加局部类，保持现有企业后台密度并允许移动端自然换行：

```css
.dashboardReadinessSummary {
  min-width: 0;
}

.dashboardReadinessSummary .panelDescription {
  margin: -2px 0 12px;
  color: #667489;
  font-size: 13px;
}

.dashboardReadinessSummary .panelFooterAction {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
```

- [ ] **Step 2: 验证 System Admin 测试**

Run: `npm --prefix admin-web/system-admin test -- --run`

Expected: 全部 PASS，无未处理错误。

- [ ] **Step 3: 验证边界测试和生产构建**

Run: `node admin-web/scripts/admin-boundary.test.mjs`

Expected: PASS，Customer/System Admin 边界保持不变。

Run: `npm --prefix admin-web/system-admin run build`

Expected: 构建成功，无 TypeScript 错误。

- [ ] **Step 4: 检查改动范围与敏感信息**

Run: `git diff --check`

Expected: 无输出。

Run: `git diff | rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET"`

Expected: 无输出。

- [ ] **Step 5: 提交实现**

```bash
git add admin-web/system-admin/src/pages/DashboardPage.tsx admin-web/system-admin/src/SystemWorkspace.tsx admin-web/system-admin/src/App.tsx admin-web/system-admin/src/system-admin.test.tsx admin-web/shared/styles/base.css
git commit -m "fix: clarify system admin readiness blockers"
```
