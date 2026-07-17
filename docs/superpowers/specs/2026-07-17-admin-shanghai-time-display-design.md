# Admin Web 上海时区中文时间显示设计

## 目标

统一 Customer Admin 与 System Admin 所有面向用户的日期时间显示，固定使用上海时区和中文格式，消除当前直接显示 ISO 字符串或依赖浏览器本地时区的问题。

## 显示规范

- 时区固定为 IANA `Asia/Shanghai`，不读取浏览器所在时区。
- 完整时间统一显示为 `2026年7月17日 17:09:07`，使用 24 小时制并显示到秒。
- 空值、无法解析的值显示 `—`，不得抛出渲染异常。
- 原始 UTC 值可放在元素 `title` 中用于技术核对，但正文不得显示 ISO `T` / `Z` 格式。
- API、数据库和请求契约继续使用 UTC/ISO 8601，不修改持久化格式。
- `datetime-local` 查询输入与提交为 ISO 的行为不在本次修改范围；本次只统一读取结果的显示。

## 实现边界

- 在 Admin Web shared 层新增一个纯函数，集中使用 `Intl.DateTimeFormat` 的 `zh-CN`、`Asia/Shanghai`、24 小时制配置，并通过 `formatToParts` 组装稳定中文格式。
- shared `DataTable` 根据字段名识别 `*_at`、`timestamp` 和 `generated_at` 等日期时间字段，统一调用共享函数，因此租户、店铺、任务、决策、审计、发布和更新时间自动覆盖。
- System Admin 自定义页面显式替换直接 ISO 或 `new Date(...).toLocaleString()`：Dashboard 聚合时间、Health 检查时间、LLM 用量与调用、配置版本、审计、发布记录。
- Customer Admin 显式替换会话时间、商品更新时间等用户界面日期时间。
- shared 决策流程回放的节点开始时间使用共享函数。
- 原始技术 JSON、API payload、审计 diff 和可折叠技术诊断内容保持协议原值，避免改变排障证据；其结构化摘要中的时间仍使用上海时间。

## 租户来源核查结论

代码存在三类组织/租户产生路径：

1. System Admin `POST /v1/system-admin/organizations` 手工创建，写入 `organization` 并产生 `system_admin.organization.create` 审计。
2. 外部系统 provision/Customer Admin launch 以外部店铺引用生成稳定 `tenant-*` ID，首次进入时写入组织和店铺。
3. 开发测试、E2E、评测与 smoke 数据直接通过测试/初始化路径写入，例如 `org-001`、`org-a`、`org-eval` 以及店铺名含 `mall-codex-*` 的记录。

2026-07-17 对 Dev System Admin 安全审计按 `system_admin.organization.create` 查询没有返回记录，因此当前 9 个租户没有可用的 System Admin 手工创建审计证据。结合命名与关联店铺，`org-*` 和 `mall-codex-*` 明确属于开发/评测数据；`tenant-*` 属于外部开通或相关联调数据；当天出现的 UUID 租户缺少创建审计，不能仅凭 ID 进一步断定操作者。本次不删除或改写任何租户数据。

## 测试与验收

- 共享函数用 UTC 跨日样例验证上海时区换算，例如 `2026-07-17T16:30:45Z` 显示为 `2026年7月18日 00:30:45`。
- 测试显式设置非上海进程时区，结果仍必须保持上海时间。
- 空值和非法值显示 `—`。
- shared DataTable 的 `created_at` / `updated_at` / `published_at` 字段不再输出原始 ISO。
- 所有直接 `toLocaleString()` 的 Admin 时间渲染点被静态回归门禁禁止，只有共享格式化函数可以使用 `Intl.DateTimeFormat`。
- Customer Admin 与 System Admin 的完整测试、移动端回归和生产构建通过。
- Dev 上线后租户创建时间、审计时间和 System Admin 聚合时间均显示中文上海时间，三路健康检查通过。

