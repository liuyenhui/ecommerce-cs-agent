# 系统后台重设计与 LLM 治理设计

日期：2026-07-14

## 1. 目标

把 System Admin 从工程样机重构为面向平台运营、技术支持、发布管理员和安全审计的真实工作台：所有页面使用真实持久化数据，按任务组织信息，补齐 LLM 配置、用量、版本发布和审计能力，并保持 Customer Admin 与 System Admin 的站点、会话和 API 鉴权域完全隔离。

详细长期设计归入 [System Admin Design](../../system-admin-design.md)。本文固定本轮实施范围、交付顺序和验收边界。

## 2. 已确认的产品决策

- 采用“任务导向完整重构”，不只为现有页面换皮。
- 桌面左侧导航可展开或收缩；每个菜单项使用 Lucide 图标。收缩态为 64px 图标栏，并提供 tooltip、焦点说明和当前项高亮。
- 移动端使用顶部应用栏和抽屉导航，不把桌面图标栏直接压缩到手机宽度。
- 系统后台使用高密度 IBM / Carbon 风格：低圆角、轻边框、清晰表格和克制状态色。
- 中文使用 `PingFang SC` / `Noto Sans SC`，英文和数字使用 `IBM Plex Sans`；技术标识使用 `IBM Plex Mono` 或系统等宽字体。
- 所有功能按独立区块分隔。Provider 连接、场景路由、参数草稿、用量统计和审计不能挤在同一个无边界内容块中。
- LLM 设置采用完整治理能力：Provider、模型、超时、重试、温度、Token 上限、熔断、恢复探测、场景路由、降级模型、连接测试、草稿、发布、回滚和审计。
- 密钥只引用 Kubernetes Secret；前端、API、数据库、审计和日志均不返回或保存明文。
- 不显示 demo 数据。无真实记录时使用结构化空态，不在前端构造示例数据或曲线。

## 3. 信息架构

系统后台固定为 9 个一级页面。

| 分组 | 页面 | 核心任务 |
| --- | --- | --- |
| 平台运营 | 系统总览 | 查看真实平台总量、阻断、告警、待发布配置和优先处理事项。 |
| 平台运营 | 租户与店铺 | 创建和治理租户、店铺、管理员与接入状态。 |
| 平台运营 | 配置完成度 | 查看商品、知识、规则、动作能力和模拟测试的上线门禁。 |
| AI 与发布 | LLM 治理 | 管理 Provider、参数、场景路由、降级、用量成本、版本和审计。 |
| AI 与发布 | 评测与发布 | 查看确定性测试、盲测、红线用例、发布审批和回滚。 |
| 排障与安全 | 决策追踪 | 查询真实决策并回放 LangGraph、上下文和动作结果。 |
| 排障与安全 | 任务中心 | 查看真实异步任务、失败原因和幂等重试。 |
| 排障与安全 | 安全审计 | 查询登录、跨租户访问、敏感查看和配置变更。 |
| 排障与安全 | 系统健康 | 查看 API、PostgreSQL、对象存储、Worker、Provider 和部署状态。 |

桌面导航展开态显示图标、分组和名称；收缩态只显示图标，但当前页、未读告警和 tooltip 保持可识别。展开偏好只保存在浏览器本地，不进入业务数据。

## 4. 页面结构

### 4.1 系统总览

首页回答“今天需要处理什么”，而不是重复所有列表。

- 第一层：上线阻断、高优先级告警、待处理任务、待发布配置。
- 第二层：活跃租户、活跃店铺、今日决策量、自动回复率、转人工率和错误率。
- 主区域：优先事项、最近发布、模型异常、运行中任务和最近决策。
- 所有总数由服务端聚合 API 返回；不得使用当前页 `items.length`。

### 4.2 租户与店铺

- 租户和店铺使用分页表格，详情使用抽屉。
- 创建、冻结、停用和管理员开通使用明确动作与二次确认。
- 列表展示业务名称为主，内部 ID 作为次级等宽文本。
- 跨租户查看和所有写操作写入系统审计。

### 4.3 配置完成度

- 按店铺汇总商品资料、知识审核、规则、动作能力、接入凭据和模拟测试。
- 每个检查项区分 `passed`、`warning`、`blocked`、`not_configured`。
- 阻断项必须显示原因、影响和下一步，不只显示红色徽标。

### 4.4 LLM 治理

LLM 治理使用四个二级页：

1. 配置与路由：Provider 连接、Secret 引用、场景主模型、降级模型和参数草稿。
2. 调用与成本：调用次数、输入/输出 Token、估算成本、P95、错误率、趋势、成本分布、失败原因和调用明细。
3. 版本记录：草稿、已验证、待发布、运行中、已回滚版本。
4. 变更审计：操作者、原因、差异摘要、连接测试和发布结果。

Provider 连接与场景模型路由必须是两个独立区块，各自包含标题、说明和表头。参数修改只保存草稿；连接测试验证草稿但不切换线上；发布成功后才更新运行版本。发布失败时继续使用原版本。

调用统计只保存和展示调用元数据、模型、业务场景、Token、耗时、状态和估算成本，不展示完整 Prompt、客户消息、模型回复或密钥。

### 4.5 评测与发布

- 展示确定性测试、盲测、红线用例、人工抽检和对比基线。
- 红线失败或严重回归时阻断发布。
- 发布记录关联模型配置、Prompt、Graph、规则版本和评测运行。
- 回滚是新的受审计操作，不删除历史版本。

### 4.6 决策追踪、任务、审计和健康

- 决策追踪默认展示脱敏摘要；查看 raw payload 需要能力、原因和单独审计。
- 任务中心只允许重试服务端标记为幂等安全且处于可重试状态的任务。
- 安全审计支持按操作者、租户、店铺、动作、敏感访问和时间筛选。
- 系统健康区分应用健康、依赖健康和部署健康；局部依赖失败显示 degraded，不伪装为整体健康。

## 5. 真实数据与环境边界

### 5.1 运行数据来源

- development 和 production 必须使用 PostgreSQL 仓库；缺少 `DATABASE_URL` 时启动失败。
- In-memory 仓库和测试夹具只允许 `APP_ENV=test`。
- 前端不生成 demo 条目、不回退到静态常量，也不把空数组转换为假统计。
- 列表总量来自服务端 `page.total`；系统级指标来自专用聚合响应。
- 图表没有真实时间序列时显示“暂无调用统计”，不绘制示例曲线。

### 5.2 已存在的模拟记录

不得按 ID、名称或消息正文猜测记录是否为 demo。若 dev 数据库已有模拟记录，应使用稳定的 `data_origin` / `environment` 标识或经审核的一次性清理清单处理。实施时不得以 `name contains demo`、`org-001` 等启发式过滤真实查询结果。

### 5.3 空态与错误态

每个数据区块区分：

- loading：数据仍在加载，不显示旧统计冒充新结果。
- empty：查询成功但没有记录，解释原因和下一步。
- permission denied：保留页面结构，说明缺少的系统能力。
- partial failure：其他区块继续可用，并明确哪个数据源失败。
- fatal error：页面级错误，提供重试和错误 ID，不泄露内部堆栈。

## 6. API 与数据设计

### 6.1 复用现有接口

- `/v1/system-admin/organizations`
- `/v1/system-admin/stores`
- `/v1/system-admin/readiness/stores`
- `/v1/system-admin/message-traces`
- `/v1/system-admin/tasks`
- `/v1/system-admin/audit-logs`
- `/v1/system-admin/health`

### 6.2 新增接口组

- `GET /v1/system-admin/dashboard-summary`
- Provider：列表、创建、修改、验证 Secret 引用和连接测试。
- LLM 配置版本：读取运行版本、创建/修改草稿、校验、提交发布和回滚。
- 场景路由：读取和修改主模型、降级模型与启用状态。
- LLM 用量：summary、timeseries、breakdown 和 invocation metadata。
- 评测与发布：eval runs、release gates、release records 和 rollback。
- 配置完成度详情：单店铺检查项与服务端聚合分布。

所有接口位于 `/v1/system-admin/*`，只接受 `agent_system_admin_session`。写接口要求 `reason` 和 `idempotency_key`；高风险操作还要求当前版本或 ETag，避免覆盖并发修改。

### 6.3 持久化对象

- `llm_provider_config`：Provider 名称、类型、端点、Secret 引用、状态和最近验证结果。
- `llm_config_version`：不可变版本元数据、状态、创建人、发布人和发布时间。
- `llm_scenario_route`：配置版本下的业务场景、主模型、降级模型和运行参数。
- `llm_connection_test`：目标草稿、操作者、状态、耗时和脱敏错误摘要。
- `llm_invocation_metric`：调用元数据、Token、耗时、状态、估算成本和维度引用。
- `release_record`：发布对象、评测门禁、运行版本、回滚引用和审计 ID。

持续状态保存在 PostgreSQL；API/Admin Pod 保持无状态。高频统计可以后续增加按小时聚合表，但第一版必须先保证原始元数据可追溯且有保留策略。

## 7. 安全与权限

- Provider Secret 只保存 namespace、Secret 名和 key 名的引用。
- API 响应不能包含 Secret 值、Authorization、Cookie、数据库连接串或完整请求头。
- `super_admin` / `release_manager` 可以修改并发布 LLM 配置；`technical_support` 默认只读并可执行连接测试；`security_auditor` 只读审计。
- 连接测试不记录 Prompt 和返回正文，只记录必要结果元数据。
- 查看调用明细不能反推出客户消息正文。
- 客户后台不出现 System Admin 入口，也不能调用任何新增系统接口。

## 8. 实施边界

本轮包含：

- System Admin 前端壳层、导航、9 个页面和统一状态组件。
- 现有系统接口的真实数据修正和服务端总量统计。
- LLM 完整治理、用量统计、版本发布和审计的 API、数据库与 UI。
- 评测/发布首页和现有评测报告的真实读取；不存在的高级审批流不扩展为通用流程引擎。
- 桌面与移动端验收、OpenAPI、系统后台设计和交接文档同步。

本轮不包含：

- 在浏览器中创建或修改 Kubernetes Secret 值。
- 展示完整 Prompt、客户消息或模型回复正文。
- 多云密钥管理系统、通用工作流引擎、企业 SSO 或 MFA。
- Customer Admin 视觉重构。

## 9. 测试与验收

### 9.1 后端

- 非 test 环境缺数据库时 fail fast；test 环境仍可显式使用 fixture。
- 聚合指标使用数据库总量，不受分页影响。
- LLM 草稿、连接测试、发布、回滚、并发冲突和权限拒绝都有自动化测试。
- Secret 值不会进入 API、数据库、日志、审计或测试快照。
- 用量统计按时间、Provider、模型、场景和租户过滤正确。

### 9.2 前端

- 9 个页面均可从导航到达；展开/收缩和移动抽屉可键盘操作。
- Provider、路由、参数、用量和审计按功能分区。
- loading、empty、permission、partial failure 和 fatal error 均有测试。
- 页面不包含 `Demo Organization`、`Demo PDD Store` 等静态回退文本。
- 桌面 `1440x900`、移动 `390x844` 无横向溢出。
- System Admin 只请求 `/v1/system-admin/auth/me`，不出现 Customer Admin 入口。

### 9.3 项目验证

- Python tests、Admin Web tests/build、OpenAPI contract tests。
- Helm lint/template 和构建后的 Nginx 配置验证。
- dev host 登录后检查真实数据、网络请求、空态和两个后台鉴权边界。
- 发布链路按项目规则执行镜像 workflow、GitOps rollout、public health 和 live smoke；本机不直接推送业务镜像。

## 10. 完成定义

只有在代码、契约、迁移、文档、桌面/移动视觉、自动化测试和 dev 实际运行均通过后，才可声明完成。任何用静态数组、demo fixture、当前页长度或假图表替代真实运行数据的页面都不满足完成定义。
