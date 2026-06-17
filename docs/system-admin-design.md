# 系统后台设计

本文定义客服 Agent 的系统管理后台。它面向平台运营、技术支持、系统管理员和安全审计人员，用于开通租户、治理全局配置、排查决策链路、监控系统健康和管理发布质量。

相关文档：

- [Customer Admin Design](customer-admin-design.md)：客户可登录后台，用于客户维护商品资料、知识审核、规则和动作能力。
- [System Architecture](system-architecture.md)：系统组件、数据流、数据模型和决策机制。
- [Application Technology Architecture](application-technology-architecture.md)：技术栈、部署方式和前后台边界。
- [HTTP API Design](http-api-design.md)：外部客服系统、客户后台 API 和系统接口边界。
- [System Architecture HTML](system-architecture.html)：交互式架构图和数据模型视图。
- [System Admin UI Prototype](system-admin-ui-prototype.html)：系统后台静态 UI 原型，用于开发阶段对齐布局、信息架构和视觉风格。

## 1. 定位与边界

系统后台不是客户后台，也不是客服对话工作台。它管理客服 Agent 平台本身，服务对象是平台方内部人员，而不是客户的客服主管或资料维护员。

| 后台 | 使用者 | 核心职责 |
| --- | --- | --- |
| 客户后台 | 客户运营、客服主管、资料维护员、知识审核员、规则运营 | 维护本组织和店铺的商品资料、价格快照、知识片段、规则、动作能力和审计查询。 |
| 系统后台 | 平台运营、技术支持、系统管理员、安全审计 | 开通和治理租户、查看跨租户状态、排查消息决策、监控任务和系统健康、管理全局模板与发布质量。 |

系统后台必须遵循以下边界：

- 不替代外部客服系统的客服工作台，不接收买家消息，也不负责真实发送回复。
- 不绕过客户权限直接修改客户业务资料；需要代运营修改时必须显式记录操作者、原因、租户、店铺、对象和差异摘要。
- 不保存明文密钥、平台密码、云凭据、LLM Key、SMTP 密码或客户生产数据导出文件。
- 不把外部系统用户、ERP 角色或电商平台账号直接视为系统后台权限来源。
- 系统后台服务必须可 k8s 无状态部署；session、任务状态、审计、配置和发布记录必须使用 PostgreSQL、Redis、对象存储或其他外部持久化能力。

## 2. 第一版目标

第一版系统后台优先解决平台上线后的真实运营问题：

1. 能开通组织、店铺和客户后台初始管理员。
2. 能查看客户是否完成资料、知识、规则和动作能力配置。
3. 能按租户、店铺、平台、时间和 `decision_id` 查询决策链路。
4. 能发现失败：资料解析失败、知识审核积压、价格过期、规则未启用、动作回调失败、上下文回填超时。
5. 能查看系统级审计、API 调用、模型调用、异步任务和部署健康状态。
6. 能为后续规则模板、灰度发布、自动化评测和安全审批预留扩展点。

第一版不做以下内容：

- 不做买家会话接待界面。
- 不做客户业务知识的批量人工替客户审核，除非后续增加代运营审批权限。
- 不做直接登录淘宝、拼多多、京东、抖音等平台后台。
- 不做供应商锁定的 SSO；后续企业 SSO 应使用 OIDC、SAML 或通用企业 IdP 模型。

## 3. 系统角色与权限

系统后台应独立于客户后台建立内部角色模型。客户后台 `organization.owner` 不等于系统后台管理员。

| 角色 | 权限范围 |
| --- | --- |
| 超级管理员 | 管理系统后台用户、全局安全策略、租户开通、全局配置和高风险操作。应尽量少量配置。 |
| 平台运营 | 开通租户、查看客户配置进度、查看资料体检和知识审核积压、处理运营问题。 |
| 技术支持 | 查询消息追踪、任务状态、API 错误、回调失败、模型错误和系统健康；默认不修改客户业务配置。 |
| 规则管理员 | 维护系统默认规则模板、动作能力模板、风险等级模板和版本发布记录。 |
| 安全审计 | 只读查看系统后台登录、权限变更、代运营操作、高风险配置变更和敏感数据访问记录。 |
| 发布管理员 | 管理 Prompt、Graph 版本、规则模板版本、评测报告和发布门禁状态。 |

权限原则：

- 系统后台账号、角色和 session 与客户后台账号隔离。
- 查看跨租户数据必须记录访问审计，尤其是 raw payload、错误详情和消息 trace。
- 写入客户租户数据必须区分“系统配置修改”和“代客户操作”，并记录业务原因。
- 高风险操作应至少要求二次确认，后续可扩展为审批流。
- 系统后台默认只展示脱敏数据；完整 raw payload 只允许技术支持或更高权限在排障场景查看。

## 4. 页面与模块

第一版系统后台建议按“平台运营、决策排障、任务运行、安全治理”组织导航。

| 模块 | 核心能力 |
| --- | --- |
| 系统首页 | 展示租户总数、活跃店铺、今日决策量、自动回复率、转人工率、错误率、待处理任务和关键告警。 |
| 租户管理 | 创建、停用、冻结组织；维护组织状态、套餐标记、联系人、开通来源和备注。 |
| 店铺管理 | 创建店铺、绑定平台、维护 `external_store_id`、平台账号引用、启用状态和资料配置进度。 |
| 客户管理员开通 | 创建初始客户管理员、重发邀请、禁用异常客户账号、查看客户登录记录。 |
| 配置完成度 | 跨租户查看商品资料、价格快照、知识审核、规则和动作能力是否满足上线条件。 |
| 资料体检总览 | 查看缺说明书、缺 SKU 图、价格过期、知识未审核、解析失败和信息冲突的租户/店铺列表。 |
| 知识审核队列总览 | 查看各租户待审核知识候选、拒绝率、审核积压时间和高风险片段数量。 |
| 规则与动作治理 | 查看店铺规则版本、系统默认规则模板、动作能力配置、风险等级、回调地址和确认要求。 |
| 消息决策追踪 | 按 `decision_id`、请求 ID、外部消息 ID、租户、店铺、平台和时间查询完整决策摘要。 |
| 上下文与动作排障 | 查看 `context_requests[]`、上下文回填、`action_request`、`action_result`、超时、重试和失败原因。 |
| 异步任务中心 | 查看资料解析、Markdown 转换、知识抽取、embedding、批量导入、评测运行等任务状态。 |
| 模型与用量 | 查看 LLM provider 状态、调用量、成本、延迟、超时、错误、token 使用和降级情况。 |
| 评测与发布门禁 | 查看 deterministic 测试、盲测、红线用例、Prompt/Graph/规则版本和发布阻断原因。 |
| API 与接入凭据 | 管理租户 API Key / Bearer Token 引用、轮换状态、最后使用时间、限流和 IP 白名单预留。 |
| Webhook 与回调 | 查看 callback 配置、签名状态、失败重试、死信记录和最近回调错误。 |
| 系统审计 | 查看系统后台登录、权限变更、跨租户访问、代运营修改、敏感数据查看和高风险变更。 |
| 系统健康 | 查看 API、Worker、PostgreSQL、Redis、对象存储、pgvector、队列、K8s deployment 和 ingress 健康。 |

## 5. UI 原型与开发规范

系统后台 UI 开发必须以 [System Admin UI Prototype](system-admin-ui-prototype.html) 为第一版视觉和信息架构参考。该原型不是生产代码，但它定义了系统后台的布局、导航分组、信息密度、状态表达和关键交互方式。

### 5.1 设计方向

系统后台采用 IBM / Carbon 式企业后台风格：

- 以白色主画布、浅灰导航层和 1px hairline 边框组织信息。
- 主操作使用蓝色，次级操作使用白底描边，危险操作使用红色。
- 信息密度偏高，优先支持平台运营和技术支持快速扫描、筛选、定位和处理问题。
- 不使用营销页式大卡片、装饰插画、渐变背景、圆角泡泡或低密度展示。
- 后台页面应像运维控制台和企业管理台，不像宣传页或客服聊天界面。

### 5.2 全局布局

第一版系统后台采用三栏工作台结构：

| 区域 | 说明 |
| --- | --- |
| 顶部栏 | 黑色固定栏，包含产品标识、租户范围选择、全局搜索、告警入口、命令入口和当前系统用户。 |
| 左侧导航 | 浅灰固定导航，按“平台运营 / 排障治理 / 发布安全”分组，不按数据库表名堆菜单。 |
| 主内容区 | 当前模块的标题、说明、主操作、指标、表格、列表和工作流详情。 |
| 右侧上下文栏 | 当前运行摘要、高优先级告警和快捷定位；窄屏时隐藏。 |

响应式规则：

- 桌面端优先保证三栏布局，右侧上下文栏用于承载全局状态和快捷入口。
- 中等宽度时左侧导航收缩为图标栏，主内容保持可读。
- 移动端隐藏右侧上下文栏，表格必须降级为关键列或列表，不允许横向溢出。
- 固定格式元素需要明确宽度、最小宽度或响应式网格，避免图标、标签、状态徽标挤压正文。

### 5.3 导航分组

左侧导航必须保持以下一级分组，除非后续有明确产品决策变更：

| 分组 | 页面 |
| --- | --- |
| 平台运营 | 系统首页、租户与店铺、配置完成度、资料与知识 |
| 排障治理 | 决策追踪、异步任务、规则与动作 |
| 发布安全 | 评测与发布、安全审计、系统健康 |

导航命名面向使用场景，不直接暴露内部表名。页面标题和导航名应保持一致，避免一个能力在多个入口重复出现。

### 5.4 页面结构

每个系统后台页面应遵循统一结构：

1. 页面头部显示英文小标签、中文页面标题、简短说明和 1-2 个主操作。
2. 页面主体先显示与当前任务相关的概览指标，再显示表格、列表或流程。
3. 高风险或阻断信息应靠前展示，不能埋在长表格底部。
4. 表格用于可排序、可筛选、可批量处理的数据；列表用于首页概览、任务摘要和右侧上下文信息。
5. 详情信息优先使用右侧抽屉，不轻易跳转新页面；创建、发布、冻结等明确动作使用模态弹窗。

系统首页必须服务平台运营的日常判断，第一屏至少包含：

- 活跃组织、今日决策量、转人工率、上线阻断等核心指标。
- 上线阻断队列。
- 配置完成度分布。
- 最近消息决策摘要。
- 运行中任务。
- 高优先级告警。

### 5.5 组件规范

系统后台组件应保持克制、稳定和可扫描：

| 组件 | 规范 |
| --- | --- |
| 按钮 | 主操作蓝底，次级操作白底描边，危险操作红底；按钮文案使用明确动词。 |
| 图标 | 优先使用 lucide 或项目统一图标库；图标服务识别，不单独承担业务含义。 |
| 状态徽标 | 使用成功、警告、错误、信息、普通五类；颜色必须有文字辅助，不能只靠颜色区分。 |
| 指标卡 | 保持直角或极小圆角，使用边框分隔，不使用重阴影。 |
| 表格 | 表头浅灰，行分隔 1px，关键字段加粗，ID 使用等宽字体。 |
| 进度条 | 用于配置完成度和检查项分布；必须同时显示百分比和说明文本。 |
| 抽屉 | 用于消息 trace、租户详情、任务详情等排障型详情。 |
| 模态 | 用于创建组织、发布版本、冻结凭据、查看 raw payload 申请等明确动作。 |
| Toast | 只反馈操作已记录、已保存、已切换等轻量结果，不承载长错误说明。 |

颜色语义：

- 蓝色：主操作、当前导航、进度、信息态。
- 绿色：通过、健康、已完成。
- 黄色：警告、待处理、需复核。
- 红色：阻断、失败、冻结、高风险。
- 灰色：背景层、分隔线、次级说明和禁用状态。

### 5.6 关键交互

系统后台第一版至少实现以下交互：

- 左侧导航切换页面，当前页面高亮。
- 顶部租户范围选择影响右侧上下文摘要和页面查询范围。
- 全局搜索可按 `decision_id`、请求 ID、外部消息 ID、组织和店铺定位数据。
- 决策追踪、租户详情和任务详情使用抽屉展示。
- 创建组织、邀请客户管理员、发布版本、冻结凭据等操作使用模态确认。
- 高风险操作必须要求原因或二次确认，并写入系统审计。
- 页面筛选、分段控件和状态过滤应可操作，不能只是静态装饰。

交互必须服务真实工作流：开通租户、检查上线阻断、定位消息决策、重试幂等安全任务、查看评测阻断、审计高风险操作。

### 5.7 文案与信息表达

系统后台文案面向内部平台人员：

- 使用“租户、店铺、决策、上下文、动作、评测、发布、审计”等系统术语。
- 状态说明必须给出原因，例如“价格快照过期”“等待订单上下文”“红线用例失败”。
- 错误信息应说明影响和建议动作，不能只显示错误码。
- 涉及安全和隐私时必须明确提示审计、脱敏和权限边界。
- 避免宣传口吻，避免泛化文案，例如“提升效率”“智能赋能”。

### 5.8 前端实现验收

实现系统后台 UI 时，除业务测试外还应满足以下视觉和交互验收：

- 桌面端、窄桌面端和移动端没有文字重叠、横向溢出或不可点击主操作。
- 系统首页、租户与店铺、配置完成度、决策追踪、异步任务、规则与动作、评测与发布、安全审计、系统健康都能从左侧导航到达。
- 所有页面都有一致的页面头部、主操作位置、表格样式、状态徽标和空状态/错误状态。
- 抽屉、模态、Toast、筛选、全局搜索和导航高亮有可验证交互。
- 危险操作使用红色和二次确认，不和普通保存、查看、导出混用。
- 真实实现如果使用 Ant Design 或其他组件库，视觉 token 必须覆盖到接近原型的 Carbon 风格，不能直接落成默认 Ant Design 风格。

## 6. 核心工作流

### 6.1 租户开通

1. 平台运营在系统后台创建 `organization`。
2. 为组织创建一个或多个 `store`，选择平台类型并填写外部引用字段。
3. 创建客户后台初始管理员邀请。
4. 系统生成开通检查项：商品资料、价格快照、知识审核、规则配置、动作能力配置、API 接入。
5. 客户进入客户后台完成资料和配置；系统后台只查看进度和异常。

### 6.2 上线前检查

1. 平台运营打开配置完成度页面。
2. 系统按店铺汇总资料体检、知识审核、规则状态、动作能力和最近决策测试结果。
3. 缺失项标记为阻断、警告或提示。
4. 运营可以把问题分派给客户或内部技术支持。
5. 达到上线条件后，店铺标记为可接入或可灰度。

### 6.3 消息决策排障

1. 技术支持用 `decision_id`、外部消息 ID 或请求 ID 定位记录。
2. 系统展示 ingest、normalization、retrieval、generation、risk_and_policy、persistence、feedback 分段摘要。
3. 若存在 `context_requests[]`，展示缺失上下文、回填状态、幂等键和超时原因。
4. 若存在 `action_request`，展示动作类型、payload 摘要、风险等级、外部执行结果和失败原因。
5. 默认不展示 raw payload；需要查看时必须二次确认并写审计。

### 6.4 异步任务排障

1. 技术支持按租户、任务类型、状态、时间查询任务。
2. 系统展示输入引用、输出引用、错误堆栈摘要、重试次数和下次重试时间。
3. 支持对幂等安全的任务执行重试。
4. 不支持在系统后台直接编辑任务 payload；需要修复数据时走明确的数据修复流程并写审计。

### 6.5 发布质量检查

1. 发布管理员查看待发布的 Prompt、Graph、规则模板或模型配置版本。
2. 系统展示 deterministic 测试、盲测、红线用例和人工抽检结果。
3. 红线失败或严重回归时阻断发布。
4. 发布通过后记录版本、操作者、时间、评测摘要和回滚入口。

## 7. 系统后台 API 分组

系统后台 API 建议与客户后台 API 分组隔离，避免客户后台 session 获得系统级能力。路径可以使用 `/v1/system-admin/*`。

| 分组 | 接口方向 | 说明 |
| --- | --- | --- |
| 系统登录 | `POST /v1/system-admin/auth/login`、`POST /v1/system-admin/auth/logout`、`GET /v1/system-admin/auth/me` | 系统后台登录、退出和当前系统用户信息。 |
| 系统用户 | `GET /v1/system-admin/users`、`POST /v1/system-admin/users`、`PATCH /v1/system-admin/users/{user_id}` | 管理系统后台账号、角色和状态。 |
| 租户管理 | `GET /v1/system-admin/organizations`、`POST /v1/system-admin/organizations`、`PATCH /v1/system-admin/organizations/{organization_id}` | 创建、停用、冻结和查看组织。 |
| 店铺管理 | `GET /v1/system-admin/stores`、`POST /v1/system-admin/stores`、`PATCH /v1/system-admin/stores/{store_id}` | 创建店铺、维护平台、外部引用和启用状态。 |
| 客户管理员 | `POST /v1/system-admin/organizations/{organization_id}/admin-invitations`、`PATCH /v1/system-admin/admin-users/{user_id}` | 邀请、禁用或恢复客户后台管理员。 |
| 配置完成度 | `GET /v1/system-admin/readiness/stores`、`GET /v1/system-admin/readiness/stores/{store_id}` | 跨租户查看上线检查项。 |
| 资料体检 | `GET /v1/system-admin/product-health` | 汇总资料缺口、价格过期、解析失败和知识未审核状态。 |
| 规则治理 | `GET /v1/system-admin/rules`、`POST /v1/system-admin/rule-templates`、`PATCH /v1/system-admin/rule-templates/{template_id}` | 查看规则状态，维护系统默认规则模板。 |
| 动作治理 | `GET /v1/system-admin/action-capabilities`、`POST /v1/system-admin/action-templates` | 查看动作能力和维护默认动作模板。 |
| 决策追踪 | `GET /v1/system-admin/message-traces`、`GET /v1/system-admin/message-traces/{decision_id}` | 跨租户查询消息决策摘要和排障信息。 |
| 任务中心 | `GET /v1/system-admin/tasks`、`POST /v1/system-admin/tasks/{task_id}/retry` | 查看和重试幂等安全任务。 |
| 模型与用量 | `GET /v1/system-admin/llm-usage`、`GET /v1/system-admin/provider-health` | 查看模型调用、成本、延迟和 provider 健康。 |
| 评测与发布 | `GET /v1/system-admin/eval-runs`、`GET /v1/system-admin/releases`、`POST /v1/system-admin/releases` | 查看评测报告和发布版本。 |
| API 凭据 | `GET /v1/system-admin/api-keys`、`POST /v1/system-admin/api-keys/{key_id}/rotate` | 管理租户接入凭据引用和轮换状态。 |
| 审计 | `GET /v1/system-admin/audit-logs` | 查询系统后台操作、跨租户访问和敏感数据查看记录。 |
| 健康检查 | `GET /v1/system-admin/health` | 汇总 API、Worker、存储、队列和部署健康。 |

接口约束：

- 系统后台 API 只接受系统后台 session 或系统管理员专用认证方式。
- 客户后台 session、外部系统 API Key 和外部系统 Bearer Token 不能调用系统后台 API。
- 所有跨租户查询必须带查询范围，不能默认返回全部 raw 数据。
- 写接口必须记录 `system_user_id`、目标租户、目标店铺、对象、动作、差异摘要、原因和时间。
- API 返回敏感字段时默认脱敏；密钥、token、密码和私钥永不返回明文。

### 7.1 字段级 API 契约

机器可读契约以 [OpenAPI Contract](openapi.yaml) 为准；本节固定系统 Admin 第一版实现时必须保留的字段、权限、跨租户审计和错误口径。

鉴权域隔离：

- 系统 Admin API 只接受 `agent_system_admin_session` 对应的系统 Admin session。
- 客户 Admin session、外部系统 API Key / Bearer Token 不能调用 `/v1/system-admin/*`。
- 系统 Admin session 不能调用 `/v1/admin/*` 伪装客户用户；代客户操作必须走系统后台专用接口并记录 `actor_system_user_id`、原因和目标租户。

统一分页和筛选：

- 列表接口统一使用 `page` / `page_size`，`page` 从 1 开始，`page_size` 默认 20、最大 100。
- 统一筛选字段为 `organization_id`、`store_id`、`status`、`role`、`created_at_from`、`created_at_to`。
- 消息追踪额外支持 `decision_id`、`external_message_id`；任务额外支持 `task_type`；审计额外支持 `actor_user_id`、`sensitive_access`。
- 跨租户查询必须显式带查询范围或明确排障定位字段；查看 raw payload 必须提供 `reason`。

| 接口 | 权限要求 | 请求关键字段 | 响应关键字段 | 审计要求 | 分页 / 筛选 | 主要错误 |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/system-admin/auth/me` | 已登录系统 Admin | Cookie session | `user.system_user_id`、`email`、`roles`、`capabilities` | 可记录登录态校验，不记录敏感字段 | 无 | 401 |
| `GET /v1/system-admin/users` | 超级管理员、安全审计 | `status`、`role`、`page`、`page_size` | `items[].system_user_id`、`email`、`roles`、`status`、`last_login_at`、`page_info` | 查询系统账号可写安全审计 | `status`、`role`、分页 | 401、403 |
| `POST /v1/system-admin/users` | 超级管理员 | `email`、`display_name`、`roles`、`reason`、`idempotency_key` | `user`、`audit_log_id` | 必须记录创建原因、授予角色和操作者 | 无 | 401、403、409、422、`ROLE_FORBIDDEN`、`AUDIT_REASON_REQUIRED` |
| `GET /v1/system-admin/organizations` | 平台运营、技术支持、安全审计 | `status`、`created_at_from`、`created_at_to`、`page`、`page_size` | `items[].organization_id`、`name`、`status`、`external_ref`、`created_at`、`page_info` | 跨租户列表查询写访问审计 | 状态、时间、分页 | 401、403 |
| `POST /v1/system-admin/organizations` | 平台运营或更高权限 | `name`、`status`、`external_ref`、`contact`、`reason`、`idempotency_key` | `organization`、`audit_log_id` | 必须记录开通原因和差异摘要 | 无 | 401、403、409、422、`AUDIT_REASON_REQUIRED` |
| `GET /v1/system-admin/stores` | 平台运营、技术支持、安全审计 | `organization_id`、`store_id`、`status`、时间、分页 | `items[].store_id`、`organization_id`、`platform`、`external_store_id`、`readiness_status`、`page_info` | 跨租户查询写访问审计 | 组织、店铺、状态、时间、分页 | 401、403、`TENANT_SCOPE_REQUIRED` |
| `POST /v1/system-admin/stores` | 平台运营或更高权限 | `organization_id`、`name`、`platform`、`external_store_id`、`status`、`reason`、`idempotency_key` | `store`、`audit_log_id` | 必须记录目标组织、店铺和开通原因 | 无 | 401、403、404、409、422 |
| `GET /v1/system-admin/readiness/stores` | 平台运营、技术支持、安全审计 | `organization_id`、`store_id`、`status`、`page`、`page_size` | `items[].organization_id`、`store_id`、`status`、`checks[]`、`updated_at`、`page_info` | 跨租户 readiness 查询写访问审计 | 组织、店铺、状态、分页 | 401、403 |
| `GET /v1/system-admin/message-traces` | 技术支持或更高权限；raw payload 需专门能力 | `organization_id`、`store_id`、`decision_id`、`external_message_id`、`include_raw_payload`、`reason`、时间、分页 | `items[].decision_id`、`organization_id`、`store_id`、`action`、`risk_level`、`sensitive_access`、`created_at`、`page_info` | 跨租户查询必须写审计；`include_raw_payload=true` 必须记录 `reason` 和 `sensitive_access=true` | 组织、店铺、决策、消息、时间、分页 | 401、403、422、`RAW_PAYLOAD_ACCESS_DENIED`、`AUDIT_REASON_REQUIRED` |
| `GET /v1/system-admin/message-traces/{decision_id}` | 技术支持或更高权限 | `include_raw_payload`、`reason` | `trace`、`raw_payload`、`audit_log_id` | 查看详情写跨租户审计；raw payload 访问必须单独审计 | 无 | 401、403、404、422、`RAW_PAYLOAD_ACCESS_DENIED` |
| `GET /v1/system-admin/tasks` | 技术支持、发布管理员、安全审计 | `organization_id`、`store_id`、`task_type`、`status`、时间、分页 | `items[].task_id`、`task_type`、`status`、`input_ref`、`output_ref`、`error_summary`、`retry_count`、`page_info` | 跨租户任务查询写访问审计 | 组织、店铺、任务类型、状态、时间、分页 | 401、403 |
| `POST /v1/system-admin/tasks/{task_id}/retry` | 技术支持或发布管理员 | `idempotency_key`、`reason` | `task_id`、`status`、`audit_log_id` | 必须记录重试原因、幂等键和目标任务 | 无 | 401、403、404、409、422、`IDEMPOTENCY_CONFLICT` |
| `GET /v1/system-admin/audit-logs` | 安全审计、超级管理员 | `organization_id`、`store_id`、`actor_user_id`、`sensitive_access`、时间、分页 | `items[].audit_log_id`、`actor_system_user_id`、`organization_id`、`store_id`、`object_type`、`object_id`、`action`、`reason`、`diff_summary`、`sensitive_access`、`created_at`、`page_info` | 查询审计日志本身可写二级审计；不得返回明文 secret | 组织、店铺、操作者、敏感访问、时间、分页 | 401、403 |
| `GET /v1/system-admin/health` | 技术支持、发布管理员、超级管理员 | 无 | `status`、`checked_at`、`dependencies[].name`、`status`、`message`、`checked_at` | 可记录高权限健康查看；不返回密钥、连接串、token | 无 | 401、403、500 |

统一错误响应：

- 401：未登录、系统 Admin session 缺失或失效。
- 403：已登录但没有系统角色、跨租户或敏感数据权限；业务 code 可用 `TENANT_SCOPE_REQUIRED`、`ROLE_FORBIDDEN`、`RAW_PAYLOAD_ACCESS_DENIED`。
- 404：目标租户、店铺、决策、任务或用户不存在。
- 409：幂等键、唯一约束或资源状态冲突；业务 code 可用 `IDEMPOTENCY_CONFLICT`。
- 422：字段校验失败、缺少审计原因或 raw payload 访问原因；业务 code 可用 `AUDIT_REASON_REQUIRED`。
- 429：登录、查询或高风险操作触发限流。
- 500：服务端错误；响应不得包含密钥、Cookie、请求头、数据库连接串或完整 raw payload。

系统审计字段必须至少覆盖：

| 字段 | 含义 |
| --- | --- |
| `actor_system_user_id` | 系统 Admin 操作者 ID；系统后台审计必填。 |
| `actor_admin_user_id` | 代客户操作涉及客户用户时可填写；普通系统后台操作为 `null`。 |
| `organization_id` | 目标组织 ID；系统级全局操作可为 `null`。 |
| `store_id` | 目标店铺 ID；组织级或全局操作可为 `null`。 |
| `object_type` / `object_id` | 被访问或变更的对象类型和 ID。 |
| `action` | `login`、`create`、`update`、`retry`、`cross_tenant_read`、`sensitive_read` 等动作。 |
| `reason` | 跨租户排障、代运营修改、高风险操作和 raw payload 访问原因。 |
| `diff_summary` | 变更摘要、角色变化、状态变化或任务重试摘要；不保存明文 secret。 |
| `sensitive_access` | 是否涉及 raw payload、错误详情、权限数据、跨租户数据或敏感字段查看。 |
| `created_at` | 审计记录创建时间。 |

## 8. 数据模型补充

系统后台可以复用现有业务表，但需要补充平台治理类表。命名可在实现时调整，但职责应保持清晰。

| 建议对象 | 职责 |
| --- | --- |
| `system_admin_user` | 系统后台登录用户，保存邮箱、姓名、状态、最近登录和凭证引用。 |
| `system_admin_role` | 系统后台角色定义，如超级管理员、平台运营、技术支持、安全审计。 |
| `system_admin_session` | 系统后台会话、刷新令牌、过期时间、登录 IP 摘要和审计引用。 |
| `system_audit_log` | 系统后台操作审计，记录跨租户访问、权限变更、代运营修改和敏感数据查看。 |
| `tenant_readiness_check` | 租户/店铺上线检查项快照，包括资料、知识、规则、动作能力和 API 接入状态。 |
| `system_rule_template` | 系统默认规则模板、版本、适用平台、风险等级和发布状态。 |
| `system_action_template` | 系统默认动作能力模板、`action_type`、payload schema、风险等级和确认要求。 |
| `background_task` | 后台任务状态、输入输出引用、重试次数、错误摘要和幂等键。 |
| `provider_health_snapshot` | LLM、对象存储、队列、数据库等依赖的健康状态和错误摘要。 |
| `release_record` | Prompt、Graph、规则模板、模型配置等发布记录和回滚引用。 |
| `eval_run` | 自动化测试、盲测、红线用例运行结果、报告路径和门禁状态。 |

数据模型原则：

- 系统后台用户和客户后台用户分表或至少分权限域，不能混用角色。
- 所有代客户写操作都必须能回溯到系统用户和目标客户对象。
- 系统审计日志不保存明文 secret，不保存完整敏感 payload。
- 任务和发布记录必须持久化，不能依赖单个 Worker 内存。
- 多租户查询要通过 `organization_id`、`store_id` 和权限过滤显式约束范围。

## 9. 安全与合规

系统后台权限高于客户后台，第一版必须内置安全约束：

- 默认最小权限，超级管理员账号数量受控。
- 登录、失败登录、权限变更、跨租户访问和敏感字段查看必须写审计。
- 原始消息、订单、地址、手机号、Cookie、请求头、平台凭证和外部系统 token 默认不展示。
- API Key 只展示名称、前后缀、状态、创建时间、最后使用时间和轮换状态，不展示明文。
- Secret 值只能存在 GitHub Secrets、Kubernetes Secrets 或批准的外部 secret manager；系统后台只保存引用。
- 导出功能默认关闭；如果后续开放，必须脱敏、限权、限时，并记录下载审计。
- 高风险操作包括停用租户、轮换凭据、修改全局规则模板、发布新 Graph/Prompt、查看 raw payload、代客户修改规则或动作能力。

## 10. 第一版验收口径

第一版系统后台设计成立的最低验收口径：

- 系统管理员可以登录独立系统后台，客户后台账号不能登录系统后台。
- 平台运营可以创建组织、店铺和客户后台初始管理员邀请。
- 系统后台可以查看各店铺资料、知识、规则、动作能力和 API 接入完成度。
- 技术支持可以按 `decision_id`、请求 ID 或外部消息 ID 查询消息决策摘要。
- 系统后台可以查看资料解析、知识抽取、embedding、批量导入和评测任务状态。
- 系统后台可以查看 LLM provider、API、Worker、数据库、对象存储和队列健康状态。
- 系统后台关键写操作、跨租户查询和敏感数据查看都有审计。
- API Key、Secret、平台凭证、SMTP 密码、LLM Key 和私钥不以明文出现在数据库、文档、日志或前端响应。
- 系统后台服务本身无状态，所有持续状态存入外部持久化组件。
- 系统后台 UI 与 [System Admin UI Prototype](system-admin-ui-prototype.html) 的布局、导航分组、状态表达、操作位置和信息密度保持一致。
- 桌面、窄桌面和移动视口均无文字重叠、横向溢出或主流程不可用问题。

## 11. 后续增强

后续可以逐步加入：

- MFA、企业 SSO、细粒度审批流和 break-glass 访问机制。
- 规则灰度、A/B 测试、OPA/Rego 策略即代码。
- 自动化代运营工单、客户问题分派和 SLA 跟踪。
- 更完整的成本归因、租户用量计费和异常调用告警。
- Connector 主动查询治理、回调死信重放和接入沙箱。
- 数据保留策略、脱敏导出、审计报表和合规留存。
