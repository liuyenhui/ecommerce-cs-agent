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
| 客户后台 | 客户运营、客服主管、资料维护员、知识审核员、规则运营 | 维护本租户和店铺的商品资料、价格快照、知识片段、规则、动作能力和审计查询。 |
| 系统后台 | 平台运营、技术支持、系统管理员、安全审计 | 开通和治理租户、查看跨租户状态、排查消息决策、监控任务和系统健康、管理全局模板与发布质量。 |

系统后台必须遵循以下边界：

- 不替代外部客服系统的客服工作台，不接收买家消息，也不负责真实发送回复。
- 不绕过客户权限直接修改客户业务资料；需要代运营修改时必须显式记录操作者、原因、租户、店铺、对象和差异摘要。
- 不保存明文密钥、平台密码、云凭据、LLM Key、SMTP 密码或客户生产数据导出文件。
- 不把外部系统用户、ERP 角色或电商平台账号直接视为系统后台权限来源。
- 系统后台服务必须可 k8s 无状态部署；session、任务状态、审计、配置和发布记录必须使用 PostgreSQL、Redis、对象存储或其他外部持久化能力。
- 系统后台必须部署为独立 Web 站点，dev 主域名为 `system-admin.ecommerce-cs-agent-dev.fcihome.com`；`ops-admin.ecommerce-cs-agent-dev.fcihome.com` 只作为可选别名。
- 系统后台不得挂在客户后台侧栏或同一个前端 shell 里；客户后台账号、客户后台 Cookie 和外部系统 token 都不能进入系统后台。

## 2. 第一版目标

第一版系统后台优先解决平台上线后的真实运营问题：

1. 能开通租户和店铺，并展示、核验经批准部署流程配置的客户后台初始管理员账号准备状态；不提供 UI 邀请或开通动作。
2. 能查看客户是否完成商品资料、价格快照、知识审核和 API 接入四项当前可计算配置。
3. 能按租户、店铺、平台、时间和 `decision_id` 查询决策链路。
4. 能发现失败：资料解析失败、知识审核积压、价格过期、后台任务失败和上下文回填超时。
5. 能查看系统级审计、API 调用、模型调用、异步任务和当前健康依赖状态。
6. 能为后续规则模板、灰度发布、自动化评测和安全审批预留扩展点。

第一版不做以下内容：

- 不做买家会话接待界面。
- 不做客户业务知识的批量人工替客户审核，除非后续增加代运营审批权限。
- 不做直接登录淘宝、拼多多、京东、抖音等平台后台。
- 不做供应商锁定的 SSO；后续企业 SSO 应使用 OIDC、SAML 或通用企业 IdP 模型。

## 3. 系统角色与权限

系统后台应独立于客户后台建立内部角色模型。客户后台 `tenant.owner` 不等于系统后台管理员。

| 角色 | 权限范围 |
| --- | --- |
| 超级管理员 | 管理系统后台用户、全局安全策略、租户开通、全局配置和高风险操作。应尽量少量配置。 |
| 平台运营 | 开通租户、查看客户配置进度、查看资料体检和知识审核积压、处理运营问题。 |
| 技术支持 | 查询消息追踪、任务状态、API 错误、回调失败、模型错误和系统健康；默认不修改客户业务配置。 |
| 规则管理员（后续角色） | 平台级规则模板、动作模板和风险等级模板尚无当前 System Admin API；实现对应能力后再启用该角色。 |
| 安全审计 | 只读查看系统后台登录、权限变更、代运营操作、高风险配置变更和敏感数据访问记录。 |
| 发布管理员 | 管理 LLM 配置版本、绑定的评测快照、发布记录和回滚。Prompt、Graph、规则模板的通用发布能力属于后续范围。 |

权限原则：

- 系统后台账号、角色和 session 与客户后台账号隔离。
- 系统后台登录态使用系统后台专用 HttpOnly Cookie，例如 `agent_system_admin_session`；不得复用客户后台 `agent_admin_session`。
- 查看跨租户数据必须记录访问审计，尤其是 raw payload、错误详情和消息 trace。
- 写入客户租户数据必须区分“系统配置修改”和“代客户操作”，并记录业务原因。
- 高风险操作应至少要求二次确认，后续可扩展为审批流。
- 系统后台默认只展示脱敏数据；完整 raw payload 只允许技术支持或更高权限在排障场景查看。

## 4. 页面与模块

第一版系统后台按平台运营、AI 与发布、排障与安全三组任务导航。一级菜单固定为系统总览、租户与店铺、配置完成度、LLM 治理、评测与发布、决策追踪、任务中心、安全审计和系统健康；细分能力在对应页面内使用二级页或详情抽屉，不继续扩张一级菜单。

| 模块 | 核心能力 |
| --- | --- |
| 系统首页 | 展示租户总数、活跃店铺、今日决策量、自动回复率、转人工率、错误率、待处理任务和关键告警。 |
| 租户与店铺 | 使用租户优先的单一层级列表查看组织及其所属店铺：租户为可展开主行，店铺为缩进子行；统一按租户分页，点击租户或店铺打开对应详情抽屉。当前创建接口保留，停用、冻结和状态 PATCH 尚未实现。 |
| 客户管理员开通（后续候选，当前不可用） | 后续可评估初始客户管理员邀请、重发邀请、禁用异常客户账号和查看客户登录记录；当前 System Admin 不提供这些接口。 |
| 配置完成度 | 使用按店铺分页的可展开列表跨租户查看商品资料、价格快照、知识审核和 API 接入四个真实检查项。店铺主行默认收起并展示状态和未通过项数量；展开后显示检查项、原因、影响和下一步。规则与动作能力当前不返回伪造 ready 状态。 |
| 资料体检总览（后续增强） | 当前只通过配置完成度聚合商品、价格、知识和 API 集成四项；更细的说明书/SKU/解析冲突尚无独立 System Admin API。 |
| 知识审核队列总览（后续增强） | 当前没有独立跨租户知识队列 API。 |
| 规则与动作治理（后续增强） | 当前没有平台级规则模板或动作模板 System Admin API。 |
| 消息决策追踪 | 按 `decision_id`、请求 ID、外部消息 ID、租户、店铺、平台和时间查询完整决策摘要。 |
| 上下文与动作排障 | 查看 `context_requests[]`、上下文回填、`action_request`、`action_result`、超时、重试和失败原因。 |
| 异步任务中心 | 查看真实 `background_task` 的任务类型、状态、重试能力和错误摘要；不把不存在的独立评测工作流包装为当前能力。 |
| LLM 治理 | 管理 LLM Provider、Kubernetes Secret 引用、模型参数、场景主/降级路由、连接测试、草稿、发布、回滚、调用量、成本、延迟、错误、Token 和审计。 |
| 评测与发布 | 当前只展示 LLM 配置版本、提交发布时绑定的评测快照 / `evaluation_run_id`，以及 `/v1/system-admin/llm/releases` 发布记录。没有独立评测 list/create，也没有通用 Prompt、Graph 或规则发布工作流。 |
| API 与接入凭据（后续增强） | 当前没有 System Admin API Key 列表或轮换 API。 |
| Webhook 与回调（后续增强） | 当前没有 System Admin callback / dead-letter 管理 API。 |
| 系统审计 | 查看系统后台登录、权限变更、跨租户访问、代运营修改、敏感数据查看和高风险变更。 |
| 系统健康 | 当前响应只有顶层 `status`、`checked_at`、`dependencies[]`；依赖项为 API、PostgreSQL 查询/pgcrypto、pgvector 和后台任务队列，每项返回 `name/status/message/checked_at`。不返回 Worker、Redis、对象存储或 K8s deployment/ingress 探针。 |

## 5. UI 原型与开发规范

系统后台 UI 开发必须以 [System Admin UI Prototype](system-admin-ui-prototype.html) 为第一版视觉和信息架构参考。该原型不是生产代码，但它定义了系统后台的布局、导航分组、信息密度、状态表达和关键交互方式。

### 5.1 设计方向

系统后台采用 IBM / Carbon 式企业后台风格：

- 以白色主画布、浅灰导航层和 1px hairline 边框租户信息。
- 主操作使用蓝色，次级操作使用白底描边，危险操作使用红色。
- 信息密度偏高，优先支持平台运营和技术支持快速扫描、筛选、定位和处理问题。
- 不使用营销页式大卡片、装饰插画、渐变背景、圆角泡泡或低密度展示。
- 后台页面应像运维控制台和企业管理台，不像宣传页或客服聊天界面。

### 5.2 全局布局

第一版系统后台采用可收缩导航、主工作区和按需上下文栏组成的工作台结构：

站点和路由口径：

- dev 系统后台主站点为 `https://system-admin.ecommerce-cs-agent-dev.fcihome.com`；如 DNS 或证书策略需要，可额外绑定 `https://ops-admin.ecommerce-cs-agent-dev.fcihome.com`。
- 系统后台登录页为系统后台专用 `/login`，登录成功后进入系统后台 shell；它不复用客户后台 `https://admin.ecommerce-cs-agent-dev.fcihome.com/login`。
- 系统后台前端路由守卫只调用 `/v1/system-admin/auth/me`；客户后台 session 缺失或存在都不能让系统后台放行。
- 系统后台如果需要代客户修改配置，必须走系统后台专用代运营接口并写 `actor_system_user_id`、原因、目标租户、目标店铺和差异摘要；不得伪装成客户用户调用 `/v1/admin/*`。

| 区域 | 说明 |
| --- | --- |
| 顶部栏 | 黑色固定栏，包含产品标识、租户范围选择、全局搜索、告警入口、命令入口和当前系统用户。 |
| 左侧导航 | 深色固定导航，按“平台运营 / AI 与发布 / 排障与安全”分组。桌面可在完整菜单与 64px 图标栏间切换；菜单统一使用 Lucide 图标；当前系统账号摘要位于导航底部，桌面折叠时隐藏、移动抽屉内保留。 |
| 主内容区 | 当前模块的标题、说明、主操作、指标、表格、列表和工作流详情。 |
| 右侧上下文栏 | 仅用于当前运行摘要、高优先级告警和快捷定位；账号摘要不占用此栏，窄屏时隐藏。 |

响应式规则：

- 桌面端优先保证导航与主工作区，只有当前任务确实需要全局状态或快捷定位时才显示右侧上下文栏，避免重复首页指标。
- 桌面导航可由用户主动在完整菜单和 64px 图标栏之间切换；中等宽度默认收缩，主内容保持可读。
- 移动端未登录时不渲染系统后台导航，系统登录页首屏必须优先展示邮箱、密码和提交按钮，不允许系统导航项在登录表单前占用固定高度。
- 移动端登录后隐藏右侧上下文栏，左侧导航改为顶部应用栏按钮触发的抽屉式导航；导航项点击后关闭抽屉，触控高度不小于 44px，表格必须降级为关键列或列表，不允许横向溢出。
- 固定格式元素需要明确宽度、最小宽度或响应式网格，避免图标、标签、状态徽标挤压正文。

### 5.3 导航分组

左侧导航必须保持以下一级分组，除非后续有明确产品决策变更：

| 分组 | 页面 |
| --- | --- |
| 平台运营 | 系统总览、租户与店铺、配置完成度 |
| AI 与发布 | LLM 治理、评测与发布 |
| 排障与安全 | 决策追踪、任务中心、安全审计、系统健康 |

导航命名面向使用场景，不直接暴露内部表名。页面标题和导航名应保持一致，避免一个能力在多个入口重复出现。

### 5.4 页面结构

每个系统后台页面应遵循统一结构：

“租户与店铺”页面不得把租户和店铺拆成左右两张独立表。页面顶部同时显示租户与店铺总数；统一列表默认展开租户的店铺子行，仅保留租户分页，保证同一租户及其店铺不跨页拆分。无店铺租户仍显示主行和明确空状态；长 ID 必须可换行并保留完整值，移动端不得产生水平溢出。

1. 页面头部显示英文小标签、中文页面标题、简短说明和 1-2 个主操作。
2. 页面主体先显示与当前任务相关的概览指标，再显示表格、列表或流程。
3. 高风险或阻断信息应靠前展示，不能埋在长表格底部。
4. 表格用于可排序、可筛选、可批量处理的数据；列表用于首页概览、任务摘要和右侧上下文信息。
5. 详情信息优先使用右侧抽屉，不轻易跳转新页面；创建、发布、冻结等明确动作使用模态弹窗。

系统首页必须服务平台运营的日常判断，第一屏至少包含：

- 活跃租户、今日决策量、转人工率、上线阻断等核心指标。
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
| 模态 | 用于创建租户、发布版本、冻结凭据、查看 raw payload 申请等明确动作。 |
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
- 全局搜索可按 `decision_id`、请求 ID、外部消息 ID、租户和店铺定位数据。
- 决策追踪、租户详情和任务详情使用抽屉展示。
- 创建租户、发布版本、冻结凭据等当前操作使用模态确认；客户管理员邀请属于后续候选，当前不可用。
- 高风险操作必须要求原因或二次确认，并写入系统审计。
- 页面筛选、分段控件和状态过滤应可操作，不能只是静态装饰。

交互必须服务真实工作流：开通租户、检查上线阻断、定位消息决策、重试幂等安全任务、查看评测阻断、审计高风险操作。

### 5.7 文案与信息表达

系统后台文案面向内部平台人员：

- 使用“租户、店铺、决策、上下文、动作、评测、发布、审计”等系统术语。
- 状态说明必须给出原因，例如“价格快照过期”“等待订单上下文”“评测快照未通过发布门禁”。
- 错误信息应说明影响和建议动作，不能只显示错误码。
- 涉及安全和隐私时必须明确提示审计、脱敏和权限边界。
- 避免宣传口吻，避免泛化文案，例如“提升效率”“智能赋能”。

### 5.8 前端实现验收

实现系统后台 UI 时，除业务测试外还应满足以下视觉和交互验收：

- 桌面端、窄桌面端和移动端没有文字重叠、横向溢出或不可点击主操作。
- 左侧导航必须实际包含且只包含这九个一级项：系统总览、租户与店铺、配置完成度、LLM 治理、评测与发布、决策追踪、任务中心、安全审计、系统健康；规则与动作不作为当前一级菜单。
- 所有页面都有一致的页面头部、主操作位置、表格样式、状态徽标和空状态/错误状态。
- 抽屉、模态、Toast、筛选、全局搜索和导航高亮有可验证交互。
- 危险操作使用红色和二次确认，不和普通保存、查看、导出混用。
- 真实实现如果使用 Ant Design 或其他组件库，视觉 token 必须覆盖到接近原型的 Carbon 风格，不能直接落成默认 Ant Design 风格。

## 6. 核心工作流

### 6.1 租户开通

1. 平台运营在系统后台创建 `tenant`。
2. 为租户创建一个或多个 `store`，选择平台类型并填写外部引用字段。
3. 当前不通过 System Admin 创建客户管理员邀请；客户初始管理员仍由部署时批准的初始账号配置建立，邀请能力属于后续候选。
4. 系统计算四个当前真实检查项：商品资料、价格快照、知识审核和 API 接入。
5. 客户进入客户后台完成资料和配置；系统后台只查看进度和异常。

### 6.2 上线前检查

1. 平台运营打开配置完成度页面。
2. 系统按店铺汇总商品资料、价格快照、知识审核和 API 接入四项结果。
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

### 6.5 LLM 配置评测绑定与发布

1. 发布管理员查看待发布的 LLM 配置版本。
2. 提交发布时携带 `evaluation_run_id`；服务端校验其持久化评测快照与同一组织、配置版本、revision/hash 绑定且门禁状态通过。
3. 当前 UI 和 API 不提供独立评测运行 list/create；评测快照只作为 LLM 配置版本的发布门禁引用。
4. 发布或回滚成功后写入 `llm_release_record`，并通过 `/v1/system-admin/llm/releases` 查看版本、操作者、时间、评测引用和回滚来源。
5. 通用 deterministic/盲测/红线报告，以及 Prompt、Graph、规则版本发布工作流均属于后续能力。

### 6.6 LLM 配置与用量治理

1. 发布管理员在“LLM 治理 / 配置与路由”分别维护 Provider 连接和场景模型路由；两个功能必须使用独立区块、表头和说明。
2. Provider 只保存端点和 Kubernetes Secret 引用，不读取、返回或持久化 Secret 明文。
3. 参数修改先保存为草稿；连接测试只验证草稿并记录操作者、耗时、结果和脱敏错误摘要，不改变运行版本。
4. 场景路由至少支持客服回复生成、知识抽取和盲测问题生成，并可配置主模型、降级模型、温度、Token 上限、超时、重试、熔断和恢复探测。
5. 发布前执行参数校验、Provider 连接检查和评测门禁；失败时继续使用原运行版本，成功后记录不可变版本和审计。
6. “调用与成本”按时间、Provider、模型、业务场景、租户和店铺统计调用次数、输入/输出 Token、估算成本、P95、错误率和失败原因。
7. 调用统计不保存或展示完整 Prompt、客户消息、模型回复和密钥；无真实统计时显示空态，不绘制示例曲线。

### 6.7 真实数据与环境边界

- development 和 production 必须使用 PostgreSQL 系统后台仓库；缺少 `DATABASE_URL` 时启动失败，不能回退到带示例租户/店铺的 In-memory 仓库。
- In-memory 仓库和 fixture 只允许显式 `APP_ENV=test`。
- 前端不得构造 demo 记录、静态统计或示例图表；列表总数使用服务端 `page.total`，平台指标使用专用聚合 API。
- 不得按 ID、名称或消息正文判断数据是否为 demo。已有模拟记录必须通过稳定来源字段或经审核的一次性清理清单处理。
- loading、真实空态、权限不足、局部失败和页面级失败必须使用不同状态表达。

## 7. 系统后台 API 分组

系统后台 API 建议与客户后台 API 分组隔离，避免客户后台 session 获得系统级能力。路径可以使用 `/v1/system-admin/*`。

| 分组 | 接口方向 | 说明 |
| --- | --- | --- |
| 系统登录 | `POST /v1/system-admin/auth/login`、`POST /v1/system-admin/auth/logout`、`GET /v1/system-admin/auth/me` | 系统后台登录、退出和当前系统用户信息。 |
| 系统用户 | `GET /v1/system-admin/users`、`POST /v1/system-admin/users` | 查看和创建系统后台账号；当前没有用户 PATCH。 |
| 组织管理 | `GET /v1/system-admin/organizations`、`POST /v1/system-admin/organizations` | 创建和查看客户组织。 |
| 店铺管理 | `GET /v1/system-admin/stores`、`POST /v1/system-admin/stores` | 创建和查看店铺、平台、外部引用和启用状态；当前没有店铺 PATCH。 |
| 配置完成度 | `GET /v1/system-admin/readiness/stores` | 跨租户查看上线检查项；以 `organization_id`、`store_id`、`status` 和页码筛选。 |
| 决策追踪 | `GET /v1/system-admin/message-traces`、`GET /v1/system-admin/message-traces/{decision_id}` | 跨租户查询消息决策摘要、LangGraph 运行回放和排障信息。 |
| 任务中心 | `GET /v1/system-admin/tasks`、`POST /v1/system-admin/tasks/{task_id}/retry` | 查看和重试幂等安全任务。 |
| 系统总览 | `GET /v1/system-admin/dashboard-summary` | 返回服务端聚合的租户、店铺、决策、阻断、任务、告警和待发布配置指标。 |
| LLM Provider | `GET/POST /v1/system-admin/llm/providers`、`PATCH /v1/system-admin/llm/providers/{provider_id}`、`POST /v1/system-admin/llm/providers/{provider_id}/connection-tests` | 管理 Provider、Secret 引用和连接测试，不返回密钥值。 |
| LLM 配置版本 | `GET /v1/system-admin/llm/config-versions`、`GET /v1/system-admin/llm/config-versions/{version_id}`、`POST /v1/system-admin/llm/config-versions/drafts`、`POST .../{version_id}/validate`、`POST .../{version_id}/submit-publish`、`POST .../{version_id}/publish`、`POST .../{version_id}/rollback` | 管理草稿、校验、评测绑定、发布、运行版本和回滚。 |
| LLM 场景路由 | `PUT` 或 `PATCH /v1/system-admin/llm/config-versions/{version_id}/routes` | 以完整集合替换草稿的主模型、降级模型与运行参数。 |
| LLM 发布记录 | `GET /v1/system-admin/llm/releases` | 按组织读取真实 `llm_release_record`，使用 HMAC cursor 分页。 |
| LLM 用量 | `GET /v1/system-admin/llm/usage/summary`、`GET /v1/system-admin/llm/usage/timeseries`、`GET /v1/system-admin/llm/usage/breakdown`、`GET /v1/system-admin/llm/usage/invocations` | 查看真实调用、Token、成本、延迟、失败和脱敏调用元数据。 |
| 审计 | `GET /v1/system-admin/audit-logs` | 查询系统后台操作、跨租户访问和敏感数据查看记录。 |
| 健康检查 | `GET /v1/system-admin/health` | 返回 `status`、`checked_at` 和 API、PostgreSQL/pgcrypto、pgvector、queue 四类 `dependencies[]`；当前没有 Worker、对象存储或部署探针字段。 |

后续候选（当前 API 与 OpenAPI 均不可用）：组织/店铺/系统用户状态 `PATCH`、客户管理员邀请/重发邀请/禁用恢复、独立评测运行 list/create workflow、deterministic/盲测/红线报告、Prompt/Graph/规则通用 release API、平台级规则/动作模板和 API 凭据轮换。实现前不得把这些候选路径作为当前能力展示或调用。

接口约束：

- 系统后台 API 只接受系统后台 session 或系统管理员专用认证方式。
- 客户后台 session、外部系统 API Key 和外部系统 Bearer Token 不能调用系统后台 API。
- 系统后台 UI 只调用 `/v1/system-admin/*` 和明确允许的只读排障接口；不得直接调用 `/v1/admin/*` 伪装客户后台操作。
- 所有跨租户查询必须带查询范围，不能默认返回全部 raw 数据。
- 写接口必须记录 `system_user_id`、目标租户、目标店铺、对象、动作、差异摘要、原因和时间。
- API 返回敏感字段时默认脱敏；密钥、token、密码和私钥永不返回明文。
- LLM 配置写接口必须携带 `reason`、`idempotency_key` 和当前版本/ETag；并发覆盖返回 409。

### 7.1 字段级 API 契约

机器可读契约以 [OpenAPI Contract](openapi.yaml) 为准；本节固定系统 Admin 第一版实现时必须保留的字段、权限、跨租户审计和错误口径。

鉴权域隔离：

- 系统 Admin API 只接受 `agent_system_admin_session` 对应的系统 Admin session。
- 客户 Admin session、外部系统 API Key / Bearer Token 不能调用 `/v1/system-admin/*`。
- 系统 Admin session 不能调用 `/v1/admin/*` 伪装客户用户；代客户操作必须走系统后台专用接口并记录 `actor_system_user_id`、原因和目标组织。

统一分页和筛选：

- 列表接口统一使用 `page` / `page_size`，`page` 从 1 开始，`page_size` 默认 20、最大 100。
- 组织列表支持 `status`；店铺与完成度支持 `organization_id`、`store_id`、`status`；任务额外支持 `task_type`。
- 消息追踪支持 `organization_id`、`store_id`、`decision_id`、`external_message_id`、`time_from`、`time_to`；审计支持 `actor_user_id`、`action`、`sensitive_access` 和相同时间边界。
- 跨组织查询必须显式带查询范围或明确排障定位字段；查看 raw payload 必须提供 `reason`。

| 接口 | 权限要求 | 请求关键字段 | 响应关键字段 | 审计要求 | 分页 / 筛选 | 主要错误 |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/system-admin/auth/me` | 已登录系统 Admin | Cookie session | `user.system_user_id`、`email`、`roles`、`capabilities` | 可记录登录态校验，不记录敏感字段 | 无 | 401 |
| `GET /v1/system-admin/users` | `super_admin`、`security_auditor` | 无查询参数 | `items[].system_user_id`、`email`、`roles`、`status`、`page_info` | 查询系统账号写安全审计 | 当前返回服务端默认第一页 | 401、403 |
| `POST /v1/system-admin/users` | 超级管理员 | `email`、`display_name`、`roles`、`reason`、`idempotency_key` | `user`、`audit_log_id` | 必须记录创建原因、授予角色和操作者 | 无 | 401、403、409、422、`ROLE_FORBIDDEN`、`AUDIT_REASON_REQUIRED` |
| `GET /v1/system-admin/organizations` | 任一有效 System Admin session | `status`、`page`、`page_size` | `items[].organization_id`、`name`、`status`、`external_ref`、`created_at`、`page_info` | 跨组织列表查询写访问审计 | 状态、分页 | 401 |
| `POST /v1/system-admin/organizations` | `super_admin`、`platform_operator` | `name`、`status`、`external_ref`、`contact`、`reason`、`idempotency_key` | `organization`、`audit_log_id` | 必须记录开通原因和差异摘要 | 无 | 401、403、409、422、`AUDIT_REASON_REQUIRED` |
| `GET /v1/system-admin/stores` | 任一有效 System Admin session | `organization_id`、`store_id`、`status`、`page`、`page_size` | `items[].store_id`、`organization_id`、`platform`、`external_store_id`、`readiness_status`、`page_info` | 跨组织查询写访问审计 | 组织、店铺、状态、分页 | 401 |
| `POST /v1/system-admin/stores` | `super_admin`、`platform_operator` | `organization_id`、`name`、`platform`、`external_store_id`、`status`、`reason`、`idempotency_key` | `store`、`audit_log_id` | 必须记录目标组织、店铺和开通原因 | 无 | 401、403、404、409、422 |
| `GET /v1/system-admin/readiness/stores` | 任一有效 System Admin session | `organization_id`、`store_id`、`status`、`page`、`page_size` | `items[].organization_id`、`store_id`、`status`、`checks[]`、`updated_at`、`page_info` | 跨组织 readiness 查询写访问审计 | 组织、店铺、状态、分页 | 401 |
| `GET /v1/system-admin/message-traces` | `super_admin`、`technical_support`、`security_auditor`；raw payload 另需 `trace:raw_payload:read` | `organization_id`、`store_id`、`decision_id`、`external_message_id`、`include_raw_payload`、`reason`、时间、分页 | `items[].decision_id`、`organization_id`、`store_id`、`action`、`risk_level`、`sensitive_access`、`created_at`、`page_info` | 跨组织查询必须写审计；`include_raw_payload=true` 必须记录 `reason` 和 `sensitive_access=true` | 至少提供组织、店铺、决策/消息或时间范围之一；分页 | 401、403、422、`RAW_PAYLOAD_ACCESS_DENIED`、`AUDIT_REASON_REQUIRED` |
| `GET /v1/system-admin/message-traces/{decision_id}` | `super_admin`、`technical_support`、`security_auditor`；raw payload 另需专门能力 | `include_raw_payload`、`reason` | `trace`、`trace.graph`、`raw_payload`、`audit_log_id` | 查看详情写跨组织审计；运行回放默认显示脱敏引用；raw payload 访问必须单独审计 | 无 | 401、403、404、422、`RAW_PAYLOAD_ACCESS_DENIED` |
| `GET /v1/system-admin/tasks` | 任一有效 System Admin session | `organization_id`、`store_id`、`task_type`、`status`、`page`、`page_size` | `items[].task_id`、`task_type`、`status`、`retryable`、`input_ref`、`output_ref`、`error_summary`、`retry_count`、`page_info` | 跨组织任务查询写访问审计 | 组织、店铺、任务类型、状态、分页 | 401 |
| `POST /v1/system-admin/tasks/{task_id}/retry` | `super_admin`、`technical_support`、`platform_operator` | `idempotency_key`、`reason` | `task_id`、`status`、`audit_log_id` | 只允许服务端标记为 `status=failed` 且 `retryable=true` 的任务；入队后 `retryable=false`，记录原因和幂等键 | 无 | 401、403、404、409、422、`IDEMPOTENCY_CONFLICT` |
| `GET /v1/system-admin/audit-logs` | 任一有效 System Admin session | `organization_id`、`store_id`、`actor_user_id`、`action`、`action_prefix`、`sensitive_access`、`time_from`、`time_to`、分页 | `items[].audit_log_id`、`actor_system_user_id`、`organization_id`、`store_id`、`object_type`、`object_id`、`action`、`reason`、`diff_summary`、`sensitive_access`、`created_at`、`page_info` | `action_prefix` 在计数与分页前由服务端过滤；查询本身写二级审计，不得返回明文 secret | 组织、店铺、操作者、动作/前缀、敏感访问、`[time_from,time_to)`、分页 | 401、422 |
| `GET /v1/system-admin/health` | 任一有效 System Admin session | 无 | `status`、`checked_at`、`dependencies[].name`、`status`、`message`、`checked_at` | 记录健康查看；不返回密钥、连接串、token | 无 | 401、500 |

### 7.2 LLM 治理契约

角色矩阵以 OpenAPI 的 `x-roles` 和服务层集合为准：

| 能力 | 允许角色 |
| --- | --- |
| Provider、配置版本、发布记录、用量读取 | `super_admin`、`release_admin`、`technical_support`、`security_auditor` |
| Provider 创建/更新、草稿/路由/校验/提交/发布/回滚 | `super_admin`、`release_admin` |
| Provider 连接测试 | `super_admin`、`release_admin`、`technical_support` |

接口与关键字段：

| 接口 | 请求关键字段 | 响应关键字段与语义 |
| --- | --- | --- |
| `GET/POST /v1/system-admin/llm/providers` | 创建：`name`、`provider_type`、`base_url`、`secret_ref{namespace,name,key}`、`enabled`、`reason`、`idempotency_key` | `LlmProvider` 返回引用和脱敏健康状态，不返回 Secret 值。 |
| `PATCH /v1/system-admin/llm/providers/{provider_id}` | `expected_revision`、可选 `name`/`enabled`、`reason`、`idempotency_key` | 只允许改名称和启用状态；`provider_type`、`base_url`、`secret_ref` 不可原地替换。 |
| `POST .../providers/{provider_id}/connection-tests` | `config_version_id`、可选 `timeout_seconds`（1–20）与 `max_tokens`（1–256）、`reason`、`idempotency_key` | 返回 `status`、`latency_ms`、安全 `error_code`、`redacted_error_message`；不返回上游请求/响应正文。 |
| `GET /v1/system-admin/llm/config-versions` | 必填 canonical UUID `organization_id`；`limit` 1–100，默认 50；可选 `cursor` | `items[]` 含 `version_id`、组织、版本号、状态、revision、hash、routes、release/evaluation 摘要；`page_info{limit,has_more,next_cursor}`。 |
| `GET /v1/system-admin/llm/releases` | 与版本列表相同，`organization_id` 必填 | 返回真实 `llm_release_record`：评测绑定、提交/发布操作者与时间、回滚来源和 revision；读取写 `llm.release.list` 审计，但不记录原始 cursor。 |
| `GET /v1/system-admin/llm/config-versions/{version_id}` | canonical UUID `version_id` | 读取单版本和完整 routes，供跨页发布记录回滚前加载。 |
| `POST /v1/system-admin/llm/config-versions/drafts` | canonical UUID `organization_id`、可选 `description`、`reason`、`idempotency_key` | 创建 `draft`；不自动伪造 Provider、路由、评测或发布记录。 |
| `PUT` / `PATCH .../{version_id}/routes` | `expected_revision`、1–32 个完整 `routes[]`、`reason`、`idempotency_key` | 两种方法都是完整替换；每条包含 scenario、主/降级 Provider-model 对、enabled、temperature、Token、超时、重试、熔断与恢复探测。 |
| `POST .../{version_id}/validate` | `expected_revision`、`reason`、`idempotency_key` | 要求三个必需场景各一次、引用 Provider 可用，且当前 Provider revision 对该草稿有通过的连接测试。 |
| `POST .../{version_id}/submit-publish` | `expected_revision`、`evaluation_run_id`、`reason`、`idempotency_key` | 评测必须是服务端可验证、绑定相同组织/配置版本/revision/hash 且门禁通过的 snapshot；成功创建真实 release record。当前没有独立 eval list/create API。 |
| `POST .../{version_id}/publish` | `expected_revision`、`reason`、`idempotency_key` | 只发布 `pending_publish`；同组织旧 running 版本转为 superseded。 |
| `POST .../{version_id}/rollback` | `reason`、`idempotency_key` | 从已发布历史创建新的 running 版本和 release record，不改写或删除原历史。 |

配置版本状态流为 `draft -> validated -> pending_publish -> running`；新版本发布后原 running 变为 `superseded`，被新回滚版本替换的运行版本可变为 `rolled_back`。release record 使用 `pending -> running -> superseded/rolled_back`。所有写请求都要求非空 `reason`、1–128 字符 `idempotency_key`；相同动作和同键同请求重放原响应，不同请求复用返回 409。带 `expected_revision` 的写入遇到旧 revision 返回 409 `stale_revision`，客户端必须重新读取，不得覆盖。

版本、发布记录和调用明细都使用服务端签发的 `payload.signature` HMAC-SHA256 不透明 cursor。cursor 绑定资源类型和规范化 scope，排他地从上一页最后一项之后继续；无下一页时 `next_cursor=null`。无签名、篡改、跨资源或跨组织/筛选复用返回 422。`LLM_CURSOR_SIGNING_KEY` 必须来自独立 Kubernetes Secret，至少 32 字节，并在所有 API replica 间一致；轮换会让旧 cursor 返回 422，调用方应从第一页重新查询。

用量四接口共享筛选：`start_at`、`end_at`（RFC3339 且 `[start_at,end_at)`）、`provider_config_id`、`model`、`scenario`、`organization_id`、`store_id`、`currency`（`CNY`/`USD`）、`status`（`succeeded`/`failed`/`timed_out`/`rejected`）和 `route_role`（`primary`/`fallback`）。`breakdown` 另要求 `group_by=provider|model|scenario|organization|store|status|error_code`；invocations 另支持 `limit` 1–500 和 cursor。汇总返回 calls、输入/输出/总 Token、P95、错误率、降级率和成本：零调用时计数为 0、比率/P95 为 null；混合币种时 `estimated_cost_micros=null`，以 `cost_by_currency` 分币种表达。调用明细只含调用/时间、Provider、模型、场景、组织/可空店铺、主降级角色、Token、延迟、状态、安全错误码、估算成本和币种，不含 Prompt、客户消息、模型回复或 Secret。当前 migration 保护 invocation history 不允许普通 UPDATE/DELETE，但仓库尚未实现按天数自动清理或可配置留存周期；留存周期仍属后续能力，不在本文虚构数值。

Secret 引用固定为 `secret_ref: {namespace, name, key}`。`namespace` 是最长 63 字符且不含点的 DNS-1123 label，`name` 是最长 253 字符且每段最长 63 字符的 DNS-1123 subdomain，`key` 是最长 253 字符的 Kubernetes data key。Pydantic/API 请求、直接 LLM service create/update 和 runtime adapter 共用同一规则，非法引用在持久化或 Secret 读取前拒绝。运行时模型凭据由 Helm `api.runtimeLlmSecretRef{name,key}` 注入，cursor 由独立 `api.cursorSigningSecretRef{name,key}` 注入；Provider 连接测试 allowlist 使用 `api.secretAccess.allowedSecretRefs[].name` 与 `keys[].{key,allowedOrigins}`，namespace 由 Pod downward API 单独注入。禁止重复 `(name,key)`，runtime tuple 必须唯一匹配 allowlist 且不得自行声明 origins，其 origin 只从 `LLM_BASE_URL` 绑定。额外 tuple 必须声明精确、无凭据的公网 HTTPS origin。禁止运行时 Secret、Provider Secret 与 cursor Secret 复用，任何 Secret 值都不进入 API 响应、数据库、日志、values 或文档。连接测试拒绝内部/Kubernetes/混合 DNS、非公网地址、重定向、origin 不匹配和 DNS rebinding，并在验证后固定 IP、保留原 SNI/Host。

持久化由 `migrations/012_system_admin_llm_governance.sql` 提供：`llm_provider_config`、`llm_config_version`、`llm_eval_run`、`llm_release_record`、`llm_scenario_route`、`llm_connection_test`、`llm_invocation_metric`。System Admin 基础审计与任务表来自 `migrations/006_system_admin_ops.sql` 的 `system_admin_audit_log` 扩展和 `background_task`。development/production 缺少 `DATABASE_URL` 或 `LLM_CURSOR_SIGNING_KEY` 时启动 fail fast；只有显式 test 环境可用 InMemory 仓库，且默认集合为空，测试必须显式注入数据。

统一错误响应：

- 401：未登录、系统 Admin session 缺失或失效。
- 403：已登录但没有系统角色、跨组织或敏感数据权限；业务 code 可用 `ORGANIZATION_SCOPE_REQUIRED`、`ROLE_FORBIDDEN`、`RAW_PAYLOAD_ACCESS_DENIED`。
- 404：目标组织、店铺、决策、任务或用户不存在。
- 409：幂等键、唯一约束或资源状态冲突；业务 code 可用 `IDEMPOTENCY_CONFLICT`。
- 422：字段校验失败、缺少审计原因或 raw payload 访问原因；业务 code 可用 `AUDIT_REASON_REQUIRED`。
- 429：登录、查询或高风险操作触发限流。
- 500：服务端错误；响应不得包含密钥、Cookie、请求头、数据库连接串或完整 raw payload。

系统审计字段必须至少覆盖：

| 字段 | 含义 |
| --- | --- |
| `actor_system_user_id` | 系统 Admin 操作者 ID；系统后台审计必填。 |
| `actor_admin_user_id` | 代客户操作涉及客户用户时可填写；普通系统后台操作为 `null`。 |
| `organization_id` | 目标客户组织 ID；系统级全局操作可为 `null`。 |
| `store_id` | 目标店铺 ID；租户级或全局操作可为 `null`。 |
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
| `tenant_readiness_check`（后续快照） | 若后续持久化完成度快照，只能基于当时真实可计算项目；当前 API 即时计算商品、价格、知识和 API 接入四项。 |
| `system_rule_template`（后续） | 平台规则模板当前没有 System Admin API。 |
| `system_action_template`（后续） | 平台动作模板当前没有 System Admin API。 |
| `background_task` | 后台任务状态、输入输出引用、重试次数、错误摘要和幂等键。 |
| `provider_health_snapshot`（后续） | 当前健康接口即时返回 API、PostgreSQL/pgcrypto、pgvector 和 queue，不持久化 Worker/存储/部署探针快照。 |
| `llm_provider_config` | Provider 类型、端点、Kubernetes Secret 引用、启用状态和最近验证结果；不保存 Secret 值。 |
| `llm_config_version` | 不可变 LLM 配置版本、草稿/运行/回滚状态、创建人、发布人和时间。 |
| `llm_scenario_route` | 配置版本下的业务场景、主模型、降级模型和运行参数。 |
| `llm_connection_test` | 连接测试目标、操作者、状态、耗时和脱敏错误摘要。 |
| `llm_invocation_metric` | 调用维度、Token、耗时、状态和估算成本；不保存完整 Prompt、客户消息或模型回复。 |
| `llm_release_record` | 当前仅记录 LLM 配置发布/回滚及其评测引用。通用 Prompt、Graph、规则 release 属于后续。 |
| `llm_eval_run` | 当前作为 LLM 配置发布绑定的持久化评测快照；没有独立 list/create workflow。通用自动化、盲测、红线报告属后续。 |

数据模型原则：

- 系统后台用户和客户后台用户分表或至少分权限域，不能混用角色。
- 所有代客户写操作都必须能回溯到系统用户和目标客户对象。
- 系统审计日志不保存明文 secret，不保存完整敏感 payload。
- 任务和发布记录必须持久化，不能依赖单个 Worker 内存。
- 跨组织查询要通过 `organization_id`、`store_id` 和权限过滤显式约束范围。

## 9. 安全与合规

系统后台权限高于客户后台，第一版必须内置安全约束：

- 默认最小权限，超级管理员账号数量受控。
- 登录、失败登录、权限变更、跨租户访问和敏感字段查看必须写审计。
- 原始消息、订单、地址、手机号、Cookie、请求头、平台凭证和外部系统 token 默认不展示。
- API Key 只展示名称、前后缀、状态、创建时间、最后使用时间和轮换状态，不展示明文。
- Secret 值只能存在 GitHub Secrets、Kubernetes Secrets 或批准的外部 secret manager；系统后台只保存引用。
- 导出功能默认关闭；如果后续开放，必须脱敏、限权、限时，并记录下载审计。
- 当前高风险操作包括轮换凭据、发布/回滚 LLM 配置、查看 raw payload 和代客户写入；停用租户、全局规则模板与 Graph/Prompt 通用发布在相应后续接口实现时再纳入。

## 10. 第一版验收口径

第一版系统后台设计成立的最低验收口径：

- 系统管理员可以登录 `system-admin.ecommerce-cs-agent-dev.fcihome.com` 独立系统后台；客户后台账号不能登录系统后台。
- `admin.ecommerce-cs-agent-dev.fcihome.com` 不展示系统后台入口，`system-admin.ecommerce-cs-agent-dev.fcihome.com` 不复用客户后台登录页、Cookie 或路由守卫。
- 平台运营可以创建租户和店铺；当前不提供客户后台初始管理员邀请，邀请能力属于后续候选。
- 系统后台可以查看各店铺商品、价格、知识和 API 接入四项完成度；规则与动作能力的独立跨租户治理属于后续增强。
- 技术支持可以按 `decision_id`、请求 ID 或外部消息 ID 查询消息决策摘要。
- 系统后台可以查看真实 `background_task` 的任务类型、状态、重试能力和错误摘要；该任务列表不等于独立评测运行 list/create workflow。
- 系统后台可以查看 LLM Provider 脱敏状态，以及 API、PostgreSQL/pgcrypto、pgvector 和任务队列健康；Worker、Redis、对象存储和 K8s 探针尚未接入当前健康响应。
- 发布管理员可以创建 LLM 配置草稿、验证 Provider、配置主/降级路由、通过评测门禁发布或回滚，并查看真实调用、Token、成本、延迟和失败统计。
- “评测与发布”当前只消费 LLM 配置版本、绑定的评测快照/`evaluation_run_id` 和 `/v1/system-admin/llm/releases`；不得展示独立评测创建、通用 Prompt/Graph/规则发布等假能力。
- development/production 缺少 PostgreSQL 时系统后台启动失败；不得回退到 Demo Organization、Demo PDD Store 或其他 In-memory 示例记录。
- 系统首页总数来自服务端聚合，列表总数来自 `page.total`；不得用当前页数组长度冒充系统总量。
- 系统后台关键写操作、跨租户查询和敏感数据查看都有审计。
- 代客户操作必须通过系统后台专用接口记录 `actor_system_user_id`、原因和目标租户，不允许伪装客户用户调用客户 Admin API。
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
- 独立评测运行 list/create、deterministic/盲测/红线报告，以及 Prompt、Graph、规则模板的通用发布门禁。
- 数据保留策略、脱敏导出、审计报表和合规留存。
