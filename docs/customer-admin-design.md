# 客户后台设计

本文定义客户可登录使用的 Admin 后台，以及进入后台前的公开宣传页和登录入口。它是第一版必备能力，用于维护 Agent 长期依赖的商品资料、规则、动作能力、知识审核和审计信息；客服问答同步接口仍只负责回复决策，不承载后台维护数据。

相关文档：

- [System Architecture](system-architecture.md)：系统组件、数据流、数据模型和决策机制。
- [Application Technology Architecture](application-technology-architecture.md)：技术栈、部署方式和前后台边界。
- [HTTP API Design](http-api-design.md)：外部客服系统和后台 API 的接口边界。
- [System Architecture HTML](system-architecture.html)：交互式架构图和数据模型视图。

## 1. 定位与边界

客户后台面向客户运营、客服主管、资料维护人员和审核人员。后台不替代外部客服系统的客服工作台，也不直接登录拼多多、淘宝、京东、抖音等电商平台后台。

| 能力 | 第一版要求 |
| --- | --- |
| 公开宣传页与登录入口 | `/` 作为产品宣传和登录入口，`/login` 承载 Agent 自有登录，`/admin` 是受保护后台。 |
| 登录与租户识别 | 客户用户可以登录后台，系统识别所属 `tenant`、可访问 `store` 和角色权限。 |
| 租户 / 店铺切换 | 用户进入后台后必须先落到明确的租户和店铺上下文；所有维护操作都绑定租户和店铺。 |
| 商品资料中心 | 维护商品、SKU、说明书、照片、视频、资料版本、适用范围和资料体检状态。 |
| 价格快照 | 查看和维护来自外部系统的当前有效价格快照；价格冲突或过期时提示风险。 |
| 知识片段审核 | 审核 Markdown 抽取出的知识候选和模拟问答，支持批准、拒绝、改写、脱敏和标注适用范围。 |
| 规则配置 | 维护店铺级自动回复规则、风险条件、转人工边界和生效版本。 |
| 动作能力配置 | 维护 `action_type`、自然语言触发表达、参数 schema、风险级别、确认要求和回调地址。 |
| 消息历史与模拟 | 查询客户消息、AI 回复、人工回复和决策路径，并手动模拟客户咨询验证 AI 决策。 |
| 审计与追踪 | 查询后台配置变更、知识审核记录、规则版本、动作能力变更和消息决策追踪入口。 |
| Web 站点边界 | 客户后台使用 `admin.ecommerce-cs-agent-dev.fcihome.com`；不得在客户后台 UI 暴露系统后台入口。 |

系统独立性规则：

- 客服 Agent 是独立系统，任何外部客服、ERP、订单、仓储或平台接入系统都应通过标准 HTTP API 单独接入。
- 客户 Admin 后台属于客服 Agent 自身，不由任何外部系统承载，也不依赖外部系统登录态、租户表、店铺表、用户表、session、token 或 Admin。
- 外部系统只能作为数据来源或动作执行方，通过 API Key / Connector Token、`store.external_store_id`、`platform_account.external_account_id`、`platform_account.auth_ref`、`listing_ref`、`external_product_id`、`external_sku_id` 等通用引用字段建立映射；公开接入不要求对方传或理解 `organization_id`。
- 外部系统数据库主键、账号 ID 或登录态不能直接作为客服 Agent 的权限来源；进入 Agent 后必须映射到 Agent 自有 `tenant`、`store` 和 Admin 成员权限。
- ERP 只能作为外部系统的一种实现示例，不能成为默认身份源、默认上游或必需部署组件。
- Customer Admin UI 面向客户时不展示“组织 / organization / org-xxx”口径；内部仍使用 `organization_id` 做租户隔离、权限校验和审计归属，页面只呈现店铺、商品资料、知识审核和审计等客户能直接理解的对象。

边界规则：

- 后台只维护 Agent 决策依赖的长期资料和配置；买家消息接收、客服工作台展示、真实发送回复、真实修改订单仍由外部客服系统负责。
- 公开宣传页只展示产品价值、能力摘要、可信产品预览和登录入口，不读取或展示任何后台租户数据。
- 后台维护的数据必须持久化到 PostgreSQL 或对象存储，Admin 服务自身保持 k8s 无状态。
- 商品说明书、照片、视频等原始资料必须保留原始文件和版本；Markdown 只是审稿稿件，不直接作为自动回复知识源。
- 自然语言动作配置只用于意图识别；真正执行外部动作时必须落到稳定 `action_type`、结构化 `payload` 和执行结果回调。
- 后台可以配置平台账号能力和 `auth_ref` 引用，但第一版不要求 Agent 主动登录电商平台后台。
- 客户后台和系统后台必须拆成不同 Web 站点、登录页、Cookie / session 名和路由守卫；客户后台不能展示“系统后台”切换入口，也不能复用系统后台登录态。

## 2. 用户、角色与权限

第一版后台需要客服 Agent 自有账号与权限模型。既有数据模型里的 `tenant`、`store`、`platform_account` 继续作为租户和店铺边界；用户登录相关表可以作为实现时补充设计：

| 建议对象 | 职责 |
| --- | --- |
| `admin_user` | Agent 后台登录用户，保存邮箱/手机号、姓名、状态、登录凭证引用和最近登录时间。 |
| `admin_membership` | 用户和 `tenant` 的成员关系，保存角色、状态和邀请来源。 |
| `admin_store_permission` | 用户可访问的 `store` 范围；租户管理员可访问租户下全部店铺。 |
| `admin_session` | Agent 后台登录会话、刷新令牌、失效时间和登录审计；实现时应使用 HttpOnly Cookie 或等价安全机制。 |
| `admin_audit_log` | 记录后台关键变更，包含操作者、租户、店铺、对象类型、对象 ID、动作、差异摘要和时间。 |

角色建议：

| 角色 | 权限范围 |
| --- | --- |
| 租户所有者 | 租户最高权限主体，负责开通和管理客户 Admin、租户设置、成员、店铺授权、平台账号能力和审计查询。 |
| 租户管理员 | 管理租户内被授权的成员、店铺、商品资料、规则和审计查询。 |
| 店铺管理员 | 管理被授权店铺的商品资料、SKU、价格快照、规则和动作能力。 |
| 资料维护员 | 上传和编辑商品资料、SKU、说明书、照片、视频和价格快照。 |
| 知识审核员 | 审核、改写、脱敏、批准或拒绝知识候选和模拟问答。 |
| 规则运营 | 配置自动回复规则、风险条件、动作能力和生效版本。 |
| 只读审计 | 查看配置、审核记录、规则版本和消息追踪，不允许修改。 |

权限原则：

- 所有后台请求都必须带有明确的租户和店铺上下文；跨店铺访问默认拒绝。
- 租户最高权限必须落在 Agent 内部 `tenant` 的 `owner` 成员关系上，不从外部系统角色直接继承。
- 修改商品资料、规则、动作能力和知识审核结果时必须写审计日志。
- 高风险规则和动作能力变更需要至少记录变更原因；是否需要二次审批可后续扩展。
- 登录态只证明用户身份，具体数据访问必须再校验租户、店铺和角色权限。

## 3. 公开宣传页与登录入口

公开宣传页是客服 Agent 自己的 Web 入口，不属于外部客服系统、ERP 或电商平台后台。它的目标是让客户理解产品能力，并以清晰的登录按钮进入 Agent 自有 Admin 登录流程。

站点口径：

- dev 客户后台主机名为 `admin.ecommerce-cs-agent-dev.fcihome.com`。
- 客户后台只承载公开宣传页、客户登录页和客户运营后台 shell。
- `www.fcihome.com` 可作为 Fcihome 总门户展示 ERP AI Agent、AI 客服、在线咨询、开发者/API 和客户入口，但只负责导航和品牌叙事；从门户跳转到客户后台后仍必须走 Agent 自有登录和 `agent_admin_session`，不能复用微信登录态或门户 Cookie。
- `open_erp_agent` 客户端可在用户完成微信/店铺登录后，通过一次性短期启动票据进入对应店铺 Customer Admin。该桥接不共享 Cookie、不上传微信/PDD session、不读取 open_erp SQLite；兑换成功后仍只建立 Agent 自有 `agent_admin_session`。
- `system-admin.ecommerce-cs-agent-dev.fcihome.com` 或 `ops-admin.ecommerce-cs-agent-dev.fcihome.com` 不属于客户后台站点；客户后台前端不提供跳转或切换入口。

路由口径：

| 路由 | 访问状态 | 行为 |
| --- | --- | --- |
| `GET /` | 公开访问 | 展示宣传页、产品能力、后台预览和登录按钮；不查询租户业务数据。 |
| `GET /login` | 未登录优先 | 展示 Agent 自有登录页；登录成功后跳转 `/admin`。 |
| `GET /admin` | 需要登录 | 已登录进入后台 shell；未登录显示客户登录页，不展示后台侧栏或系统后台入口。 |

登录后落点：

- 单租户、单店铺用户直接进入后台首页概览。
- 多租户或多店铺用户先进入租户 / 店铺选择，再进入后台首页。
- 已登录用户从 `/` 点击按钮时可以直接进入 `/admin`，但后台仍必须用 `GET /v1/admin/auth/me` 校验 session、租户、店铺和角色。

宣传页与 Admin UI/UX 口径：

- 公开宣传页面向客户时统一使用“AI”或“AI 客服”表达，不使用生硬的 Agent 概念；技术文档和内部架构说明可以继续保留 Agent 命名。
- 公开宣传页主叙事使用白话广告词，首屏推荐 H1 为“商品信息管好了，AI 客服才答得准。”，副标题说明“上传商品说明书、价格和常见问题，让 AI 先学习，再通过模拟问答检查效果。真正自动回复前，还能用规则控制范围和风险。”
- 公开宣传页视觉可更多参考 Apple 式产品展示页：轻、细、留白多、产品演示成为主视觉，一屏一个重点；字体优先使用 PingFang SC / system-ui / Inter，正文 300/400，大标题不超过 500/600。
- 公开宣传页仍保持黑白中性、大留白、清晰 AI 客服叙事、产品能力模块、可信产品预览和黑色主 CTA；链接、焦点态、轮播控制或细节状态可使用少量 Apple 蓝。
- 公开宣传页的三大卖点为“商品信息统一管理”“AI 自动学习商品知识”“AI 客服回复可控”；主流程为“上传商品说明书 → AI 学习 → 模拟问答 → AI 自动回复”。
- Hero 下方必须放一个大的产品演示轮播，展示 3 张：商品信息、AI 自学习、AI 客服回复可控；轮播可先用静态或 CSS 动画实现，后续可替换为真实截图、GIF 或视频容器。
- “怎么工作”段落必须放一个短 GIF 或等效可降级动效，演示“上传商品说明书 → AI 学习 → 模拟问答 → AI 自动回复”；暂无真实 GIF 资源时，先实现可替换的演示容器并在代码和文档中保持替换边界。
- CTA 可使用“进入客户后台”“查看演示流程”“客户登录”，末屏 CTA 可使用“先管好商品资料，再让 AI 自动回复。”
- 避免卡片墙、彩色图标堆砌、紫色渐变、装饰性光斑或圆球、消费电商风、系统后台入口、ERP 身份源，以及复制外部品牌、Logo、插画、字体、文案和品牌语义。
- Admin 后台不做 Notion 化，应继续采用 IBM / Carbon 式密集、可扫描、低阴影、1px hairline、表格 / 队列 / 配置表单优先的企业操作台规则。
- Linear 的暗色处理只用于宣传页局部产品预览或截图容器，不把整个 Admin 做成暗色系统。
- 组件库可以使用 Ant Design，但 Ant Design 是组件能力层，不是视觉风格来源；最终视觉由项目主题 token、自定义 CSS 和上述分工控制。
- 移动端未登录状态不得渲染后台左侧导航或后台菜单，登录页首屏必须优先展示邮箱、密码和提交按钮；多租户 / 多店铺用户登录后再选择业务上下文，登录页不展示组织 ID。
- 移动端登录后保留桌面左侧 rail 的信息架构，但通过顶部应用栏的菜单按钮打开抽屉式导航；导航项点击后关闭抽屉，按钮触控高度不小于 44px，长中文标签可截断或换行且不得造成横向溢出。
- Admin 后台预览仍采用 IBM / Carbon 式密集企业控制台，只作为产品演示截图或轮播内容，不让整个公开页变成后台。
- 字体使用 PingFang SC / system-ui / Inter / JetBrains Mono 等可用替代字体；不得使用外部品牌授权字体。

## 4. 页面与工作流

第一版后台页面应围绕配置闭环，而不是客服对话工作台。

| 页面 | 核心能力 |
| --- | --- |
| 公开宣传页 | 产品介绍、能力摘要、后台产品预览和登录按钮；Hero 下方展示商品信息、AI 自学习、AI 客服回复可控 3 张产品演示轮播；“怎么工作”段落使用短 GIF 或等效动效展示上传商品说明书 → AI 学习 → 模拟问答 → AI 自动回复；不展示租户数据。 |
| 登录页 | 用户使用邮箱和密码登录，或通过“使用 Fcihome Account 登录”发起客户后台 OIDC；会话续期、退出登录、登录失败提示；不要求或展示组织 ID。 |
| 店铺选择 | 显示当前用户可访问店铺；内部租户归属由 session 和权限模型确定，不在客户 UI 中展示组织 ID。 |
| 首页概览 | 展示资料缺口、待审核知识、价格过期、规则未启用、动作能力异常和最近变更。 |
| 商品资料 | 以商品主数据列表为第一入口，展示商品名称、外部商品 ID、店铺、状态、资料健康和更新时间。 |
| 资料上传 | 在商品资料页右上角通过“上传商品”弹窗上传说明书、照片、视频或文本；系统先保存原始对象并调用 AI 分析必要字段，生成导入草稿，用户确认后才创建 / 更新正式商品和资料资产。 |
| 价格快照 | 查看当前有效价格、活动价、生效时间、失效时间、来源和冲突提示。 |
| 知识审核 | 对 `product_knowledge_candidate`、`knowledge_candidate`、`knowledge_eval_case` 执行批准、拒绝、改写、脱敏和标注。 |
| 规则配置 | 维护 `rule_set`，包括规则类型、优先级、条件、动作、启用状态、版本和生效时间。 |
| 动作能力 | 维护 `action_capability`，包括 `action_type`、触发表达、payload schema、风险级别、人工确认要求和回调地址。 |
| 消息历史 | 查询本店铺客户消息、AI 回复、人工回复/反馈、决策状态、风险等级和 `trace.steps`；详情页用 X6 渲染决策路径。 |
| 模拟咨询 | 手动输入客户问题并创建 `source=simulation` 的决策记录；只展示 AI 决策和路径，不发送给真实买家。 |
| 审计与追踪 | 查询后台变更日志，并跳转到 `message-traces` 查看具体决策依据。 |

关键工作流：

1. 用户从公开宣传页点击登录，进入 Agent 自有登录页。
2. 用户登录后台，选择店铺；组织只作为内部租户隔离，不在客户 UI 中展示。
3. 资料维护员在商品资料页上传商品文档，系统保存原始对象、版本、hash 和对象引用，并调用 AI 分析标题、外部商品 ID、属性等必要字段。
4. 系统返回可编辑导入草稿；用户确认后才创建 / 更新商品主数据和资料资产。
5. 系统将可解析资料转换为 Markdown 审稿稿件，并抽取知识候选和模拟问答。
6. 知识审核员对照原文审核，批准后才写入 `knowledge_entry` 并生成 `knowledge_embedding`。
7. 规则运营配置店铺规则和动作能力，系统写入版本、审计和生效时间。
8. Agent 决策时只读取当前有效的商品资料、审核知识、价格快照、规则和动作能力。

## 5. 后台 API 分组

后台 API 使用 `/v1` 前缀，和同步决策接口共用鉴权和租户隔离原则。公开页面路由属于 Web 入口，不是外部系统接入 API；后台维护接口可以服务 Admin UI，也可以支持批量导入。

| 分组 | 接口方向 | 说明 |
| --- | --- | --- |
| 页面入口 | `GET /`、`GET /login`、`GET /admin` | 宣传页、登录页和受保护后台 shell；`/admin` 未登录必须显示客户登录页且不展示后台导航。 |
| 登录与会话 | `POST /v1/admin/auth/login`、`POST /v1/admin/auth/logout`、`GET /v1/admin/auth/me` | 登录、退出、读取当前用户、组织、店铺和角色。 |
| 组织与店铺 | `GET /v1/admin/organizations`、`GET /v1/admin/stores`、`PATCH /v1/admin/stores/{store_id}/settings` | 查看可访问组织/店铺，维护店铺设置。 |
| 用户与权限 | `GET /v1/admin/users`、`POST /v1/admin/invitations`、`PATCH /v1/admin/users/{user_id}/roles` | 租户管理员维护成员、邀请和角色。 |
| 商品资料 | `GET /v1/product-content/products`、`POST /v1/product-content/products`、`POST /v1/product-content/product-import-drafts`、`POST /v1/product-content/product-import-drafts/{draft_id}/confirm`、`POST /v1/product-content/assets`、`POST /v1/product-content/assets/{asset_id}/markdown` | 查询商品主数据列表；上传商品资料生成 AI 导入草稿；用户确认后维护商品、SKU、资料资产和 Markdown 审稿稿件。 |
| 知识审核 | `POST /v1/product-content/knowledge-candidates/{candidate_id}/reviews`、`POST /v1/knowledge/entries` | 审核候选片段，批准后形成可召回知识。 |
| 价格快照 | `POST /v1/product-content/price-snapshots`、`GET /v1/product-content/products/{product_id}/health` | 维护价格快照并检查资料健康状态。 |
| 规则配置 | `POST /v1/rules/store-rules`、`POST /v1/rules/platform-rules` | 维护店铺级和平台级规则。 |
| 动作能力 | `POST /v1/capabilities/action-capabilities` | 维护外部动作能力清单和触发表达。 |
| 消息历史与模拟 | `GET /v1/admin/message-traces`、`GET /v1/message-traces/{decision_id}`、`POST /v1/admin/message-simulations` | 查询本店铺消息历史、AI/人工回复和决策路径；模拟咨询只创建 trace，不外发。 |
| 审计查询 | `GET /v1/admin/audit-logs`、`GET /v1/message-traces/{decision_id}` | 查询后台变更和消息决策追踪。 |

接口约束：

- 后台写接口必须校验 `tenant_id`、`store_id`、角色权限和幂等键。
- 登录 session 应使用客户后台专用 HttpOnly Cookie，例如 `agent_admin_session`；服务端会话状态必须持久化到数据库、Redis 或等价外部存储，不能依赖单容器内存。
- 后台接口只信任 Agent 自有 Admin session 和成员权限；外部系统 token 只能用于外部系统接入 API，不能直接访问 Admin API。
- 客户后台路由守卫只能调用 `/v1/admin/auth/me`；不得调用 `/v1/system-admin/auth/me` 探测或复用系统后台登录态。
- `POST /v1/admin/auth/launch/exchange` 只能兑换 Agent 签发的一次性短期 launch token；成功后设置 `agent_admin_session`，不得读取或接受 open_erp、微信或 PDD Cookie。
- 后台批量导入可以复用同一接口语义，但必须返回每条记录的成功、失败和错误原因。
- 商品导入草稿确认前不得创建正式商品；上传正文、`content_base64`、Cookie、Authorization 和临时对象存储凭证不得进入审计明文。
- 同步问答接口 `POST /v1/reply-decisions` 不接收说明书、照片、视频或完整 SKU 资料；这些长期资料必须通过后台 API 维护。
- 规则、动作能力、价格快照和知识审核结果都应保留版本或审计记录，支持决策回放。

### 5.1 字段级 API 契约

机器可读契约以 [OpenAPI Contract](openapi.yaml) 为准；本节固定客户 Admin 第一版实现时必须保留的字段、权限和审计口径。

鉴权域隔离：

- 客户 Admin API 只接受 `agent_admin_session` 对应的客户 Admin session。
- 系统 Admin session、外部系统 API Key / Bearer Token 不能调用 `/v1/admin/*`。
- 客户 Admin session 不能调用 `/v1/system-admin/*`，也不能调用外部系统 `AgentApiAuth` 接口执行决策写入。

统一分页和筛选：

- 列表接口统一使用 `page` / `page_size`，`page` 从 1 开始，`page_size` 默认 20、最大 100。
- 统一筛选字段为 `tenant_id`、`store_id`、`status`、`role`、`created_at_from`、`created_at_to`。
- `tenant_id`、`store_id` 必须落在当前 session 可访问范围内；跨租户或跨店铺访问返回 403。

| 接口 | 权限要求 | 请求关键字段 | 响应关键字段 | 审计要求 | 分页 / 筛选 | 主要错误 |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/admin/auth/me` | 已登录客户 Admin | Cookie session | `user.user_id`、`email`、`roles`、`tenants[]`、`stores[]`、`active_tenant_id`、`active_store_id` | 可记录登录态校验，不记录敏感字段 | 无 | 401 |
| `GET /v1/admin/tenants` | 已登录客户 Admin | 无 | `tenants[].tenant_id`、`name`、`status` | 不需要写操作审计 | 按当前用户权限过滤 | 401、403 |
| `GET /v1/admin/stores` | 已登录客户 Admin | `tenant_id` | `stores[].store_id`、`tenant_id`、`platform`、`status` | 不需要写操作审计 | `tenant_id` | 401、403 |
| `PATCH /v1/admin/stores/{store_id}/settings` | 租户管理员、店铺管理员或规则运营 | `tenant_id`、`request_id`、`reason`、`settings` | `store_id`、`tenant_id`、`settings`、`updated_at`、`audit_log_id` | 必须写 `admin_audit_log`；高风险规则 / 动作字段必须有 `reason` | 无 | 401、403、404、422、`AUDIT_REASON_REQUIRED` |
| `GET /v1/admin/users` | 租户所有者、租户管理员、只读审计 | `tenant_id`、`store_id`、`status`、`role`、`page`、`page_size` | `items[].user_id`、`email`、`display_name`、`roles`、`store_ids`、`status`、`page_info` | 不记录敏感字段；可记录权限查询 | `tenant_id`、`store_id`、`status`、`role`、分页 | 401、403、`TENANT_SCOPE_REQUIRED` |
| `POST /v1/admin/invitations` | 租户所有者或租户管理员 | `tenant_id`、`email`、`roles`、`store_ids`、`reason`、`idempotency_key` | `invitation_id`、`email`、`roles`、`status`、`expires_at`、`audit_log_id` | 必须记录邀请对象、角色和原因；不记录邀请 token 明文 | 无 | 401、403、409、422、`ROLE_FORBIDDEN`、`IDEMPOTENCY_CONFLICT` |
| `PATCH /v1/admin/users/{user_id}/roles` | 租户所有者或租户管理员；不能越权授予自身没有的角色 | `tenant_id`、`roles`、`store_ids`、`reason`、`idempotency_key` | `user`、`audit_log_id` | 必须记录前后角色差异 `diff_summary` 和原因 | 无 | 401、403、404、409、422、`ROLE_FORBIDDEN`、`AUDIT_REASON_REQUIRED` |
| `GET /v1/admin/audit-logs` | 租户所有者、租户管理员、只读审计 | `tenant_id`、`store_id`、`object_type`、`action`、`created_at_from`、`created_at_to`、`page`、`page_size` | `items[].audit_log_id`、`actor_admin_user_id`、`tenant_id`、`store_id`、`object_type`、`object_id`、`action`、`reason`、`diff_summary`、`sensitive_access`、`created_at`、`page_info` | 查询本身可记录敏感审计查询；不能返回其他租户日志 | 租户、店铺、对象、动作、时间、分页 | 401、403、404 |
| `GET /v1/admin/message-traces` | 店铺管理员、客服主管、只读审计 | `store_id`、`decision_id`、`external_message_id`、`source`、`page`、`page_size` | `items[].decision_id`、`customer_message`、`ai_reply`、`human_reply`、`action`、`status`、`risk_level`、`trace`、`page_info` | 只返回当前 session 可访问店铺；raw payload 不返回给客户后台 | 店铺、消息、来源、分页 | 401、403、404 |
| `POST /v1/admin/message-simulations` | 店铺管理员、客服主管、知识审核员 | `store_id`、`platform`、`message.content`、可选 `context` | `source=simulation`、`decision`、`external_send.attempted=false` | 写入模拟决策 trace；不得调用外部发送动作 | 无 | 401、403、422 |

统一错误响应：

- 401：未登录、session 缺失或失效。
- 403：已登录但无租户、店铺或角色权限；业务 code 可用 `TENANT_SCOPE_REQUIRED`、`ROLE_FORBIDDEN`。
- 404：资源不存在，或资源不属于当前租户 / 店铺上下文。
- 409：幂等键或资源状态冲突；业务 code 可用 `IDEMPOTENCY_CONFLICT`。
- 422：字段校验失败、缺少变更原因；业务 code 可用 `AUDIT_REASON_REQUIRED`。
- 429：登录或高频操作限流。
- 500：服务端错误；响应不得包含密钥、Cookie、请求头或 raw payload。

审计字段必须至少覆盖：

| 字段 | 含义 |
| --- | --- |
| `actor_admin_user_id` | 客户 Admin 操作者 ID；客户后台审计必填。 |
| `actor_system_user_id` | 系统后台代客户操作时填写；普通客户后台操作为 `null`。 |
| `tenant_id` | 目标租户 ID。 |
| `store_id` | 目标店铺 ID；租户级操作可为 `null`。 |
| `object_type` / `object_id` | 被操作对象类型和 ID。 |
| `action` | `create`、`update`、`delete`、`review`、`sensitive_read` 等动作。 |
| `reason` | 高风险变更、权限变更、代客户操作和敏感访问原因。 |
| `diff_summary` | 变更前后摘要；不保存明文 secret。 |
| `sensitive_access` | 是否涉及敏感字段、raw payload 或权限数据查看。 |
| `created_at` | 审计记录创建时间。 |

## 6. 数据模型关系

后台设计复用现有核心表：

| 领域 | 相关表 |
| --- | --- |
| 租户与平台 | `tenant`、`store`、`platform_account` |
| 商品资料 | `product_master`、`product_sku`、`listing` / `store_product`、`product_asset`、`product_asset_markdown`、`product_price_snapshot` |
| 知识审核 | `knowledge_candidate`、`product_knowledge_candidate`、`knowledge_review`、`knowledge_entry`、`knowledge_embedding`、`knowledge_eval_case` |
| 规则与动作 | `rule_set`、`action_capability`、`action_request`、`action_result` |
| 决策追踪 | `decision_record`、`agent_suggestion`、`human_reply`、`feedback_label` |

实现后台登录和权限时，需要补充用户、成员、会话和审计类表。补表时必须满足：

- 可从任一后台业务记录回溯到 `tenant`，必要时回溯到 `store`。
- 与外部系统关联时只保存通用引用字段，例如 `tenant.external_ref`、`store.external_store_id`、`platform_account.external_account_id`、`platform_account.auth_ref`、`listing.external_listing_id` 和 `listing.external_sku_id`。
- 同一 `product_master` 可以关联多个平台、多个店铺、多个 listing / SKU；售卖上下文、价格、活动、规则和自动回复风险必须按 `platform + store + listing/SKU` 隔离。
- 用户权限不写入业务对象本身，业务对象只保存租户、店铺和业务字段。
- 后台审计记录保存变更摘要，不保存明文敏感密钥；平台凭证只保存 `auth_ref` 或 Secret 引用。
- 数据库是后台业务状态来源；Admin Web/API 容器不保存本地状态。

## 7. SSO 预留边界

第一版不设计 ERP 专属 SSO，也不把任何外部系统作为统一身份源。客户 Admin 默认使用 Agent 自有登录、租户、店铺、成员和 session 模型。

Customer Admin 第一版允许接入 Fcihome Account OIDC，但它只确认“是谁”，不自动创建租户、店铺或权限：

- Fcihome Account 入口只在 Customer Admin 登录页出现，按钮文案为“使用 Fcihome Account 登录”；System Admin 第一版不接 OIDC。
- OIDC 成功后只设置客户后台 `agent_admin_session`，不得设置、读取或复用 `agent_system_admin_session`。
- 已绑定 `admin_user.fcihome_account_sub` 的 active 用户可直接登录。
- 未绑定时，仅当 OIDC email 精确匹配唯一 active `admin_user`，才允许写入 `fcihome_account_sub` 并记录客户后台审计。
- 不匹配、重复匹配、未验证或缺失必要 OIDC 身份信息时必须拒绝登录，并在登录页区分“OIDC 未绑定账号”“OIDC 配置未启用”“state/PKCE 校验失败”等错误。
- `POST /v1/admin/auth/oidc/link` 必须由后端校验 OIDC code / state / PKCE 并换取 userinfo 后再绑定，不能信任前端直接提交的 subject 或 email。
- 审计只记录 provider、绑定原因、动作和对象，不记录 token、code、Cookie、client_secret、密码或完整 OIDC 响应。
- 不读取 `open_erp_agent` SQLite，不共享 Cookie，不把微信登录或任何 ERP 登录态当作 AI 客服 Admin 身份源。

后续如果需要企业 SSO，应使用 provider-agnostic 的 OIDC、SAML 或企业 IdP 接入模型，并满足：

- SSO 只证明外部身份，进入 Agent 后仍必须映射到 Agent 自有 `admin_user`、`tenant`、`store` 和成员角色。
- SSO 配置字段使用通用命名，例如 `identity_provider`、`external_subject`、`issuer`、`audience`、`role_mapping`。
- 角色映射必须显式配置，不能把外部系统角色自动视为 Agent `owner`。
- SSO 供应商可以是企业 IdP、统一账号系统或其他标准身份服务，不能写死某个 ERP、微信、PDD 或项目名。
- SSO 断言过期、签名失败、audience 不匹配或角色映射缺失时，必须拒绝登录并记录审计。

## 8. 第一版验收口径

第一版设计成立的最低验收口径：

- 公开宣传页可以匿名访问，只展示产品介绍和后台预览，不暴露租户业务数据。
- 客户后台部署在 `admin.ecommerce-cs-agent-dev.fcihome.com`，页面内不展示“系统后台”入口或切换按钮。
- 用户可以从宣传页进入 `/login`，登录成功后进入 `/admin`。
- 未登录访问 `/admin` 必须跳转 `/login`。
- 客户用户能登录后台，并看到自己有权访问的租户和店铺。
- 租户最高管理权限归属于 Agent 内部 `tenant.owner` / 租户所有者。
- 后台能维护商品、SKU、资料资产、Markdown 审稿稿件和价格快照。
- 后台能审核知识候选，批准后才进入可召回知识库。
- 后台能维护店铺规则和动作能力配置，Agent 决策读取当前有效配置。
- 后台关键写操作有操作者、租户、店铺、对象、动作和时间审计。
- 同步客服问答接口仍保持轻量，不被后台维护字段污染。
- 任一外部系统都可以按标准 API 单独接入，客服 Agent 不依赖 ERP 或其他特定外部系统。
- 客户后台 Cookie / session 与系统后台 Cookie / session 不同名、不同鉴权依赖、不同路由守卫。

## 9. 后续增强

后续可以逐步加入：

- 通用企业 SSO、MFA、细粒度审批流和高风险变更二次确认。
- 规则灰度、A/B 测试、策略即代码和 OPA/Rego。
- 更完整的指标看板、知识覆盖率分析和自动化建议。
- Connector 主动查询外部商品、订单、规则和价格。
- 批量导入任务队列、失败重试和异步通知。
