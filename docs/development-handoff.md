# 开发交接记录

本文记录会影响开发定位的最新文档变化和新会话入口。它不是新的架构来源；第一版范围以 [Development Readiness](development-readiness.md) 为准，接口契约以 [OpenAPI Contract](openapi.yaml) 为准，系统流程以 [System Architecture](system-architecture.md) 和 [System Architecture HTML](system-architecture.html) 为准。

## 最近文档更新

### 2026-07-15

- LLM 连接测试安全边界收紧：每个允许的 `(Secret name, key)` 绑定精确 Provider HTTPS origins，runtime tuple 自动绑定 `LLM_BASE_URL`；拒绝内部/Kubernetes/混合 DNS、重定向和 DNS rebinding，Provider 使用验证后固定 IP + 原始 SNI/Host。DNS 改为进程级固定 daemon worker 与有界 outstanding 队列；Kubernetes Service host 必须是 IP literal，TCP 固定该 IP、TLS 使用 `kubernetes.default.svc` 与集群 CA；HTTP CONNECT 代理同样在绝对 Deadline 内解析并固定 IP。DNS、Secret、TCP/CONNECT、TLS、HTTP 与分块响应体共享同一 20 秒绝对 Deadline，socket guard 到期即中止，TLS 初始化失败也清理 raw socket。用量分页 cursor 同时绑定版本、资源类型、组织与规范化筛选；OpenAPI 明确同 scope 复用、排他边界、无下一页为 null 及 scope 变化返回 422，四个用量接口复用同一组查询参数组件。
- LLM Provider 凭据从运行时 Secret 中分离：连接测试仅可读取 `api.secretAccess.allowedSecretRefs` 指定的专用 Secret 与 key；API Deployment 的 `LLM_API_KEY` 通过同一专用 `(name,key)` 的 `api.runtimeLlmSecretRef` / `secretKeyRef` 注入。禁止复用 `ecommerce-cs-agent-runtime`，API ServiceAccount 继续使用 namespaced `secrets/get/resourceNames` 最小权限。

### 2026-07-14

- 确认系统后台采用任务导向完整重构：9 个可达页面、可收缩 Lucide 图标导航、移动抽屉、统一状态组件和真实数据空态；development/production 禁止回退 In-memory demo 仓库，系统指标必须来自服务端总量/聚合 API。
- LLM 治理纳入第一版完整范围：Provider 与 Kubernetes Secret 引用、场景主/降级模型、运行参数、连接测试、草稿、发布/回滚、用量成本、版本和审计；不展示完整 Prompt、客户消息、模型回复或密钥。
- 新增 [系统后台重设计与 LLM 治理规格](superpowers/specs/2026-07-14-system-admin-redesign-and-llm-governance-design.md)，作为本轮实现与验收入口；详细长期约束继续归入 [System Admin Design](system-admin-design.md)。
- 新增 [系统后台重设计与 LLM 治理实施计划](superpowers/plans/2026-07-14-system-admin-redesign-and-llm-governance.md)，按真实数据边界、聚合 API、LLM 数据库与服务、API/OpenAPI、九页前端、边界回归、文档和端到端发布验证顺序实施。

### 2026-07-10

- 商品级知识自动回复必须绑定请求的稳定 `external_product_id`，PostgreSQL 召回与 evidence 门禁双重拒绝跨商品知识；请求缺少商品绑定时只允许显式 `scope=store/tenant` 且不关联商品的通用知识自动回复。
- 决策请求幂等键统一为 `organization_id + store_id + request_id`：新增前进 migration 移除旧的组织级唯一约束/索引并建立店铺级唯一索引，canonical repository 查询和 upsert 同步按店铺隔离；同一租户不同店铺可安全复用外部 `request_id`。
- 自动回复安全门禁新增可解释的中英文确定性相关性信号：只有相关审核知识、完整上下文、低风险且 `mode=auto_when_safe` 才可 `auto_reply`；`assist_first`、模拟咨询与无相关证据默认保留候选或进入上下文/转人工分支。
- 决策延续边界收紧：context refill、action result、human feedback 均使用已鉴权 Connector Principal scope 校验原决策租户/店铺；LangGraph `InMemorySaver` 改为每次 invoke 临时诊断对象，不在长期服务实例累积 thread。
- 决策 checkpoint 文档与当前实现对齐：LangGraph `InMemorySaver` 的 native checkpoint ID 只用于单次运行诊断；跨进程重算以 Repository 持久化的决策与上下文状态为依据，`resumed_from_checkpoint=true` 表示重构输入后以同一 `decision_id/thread_id` 重算，不表示从 native snapshot 原生恢复。
- 新增 [第一版需求测试矩阵](requirements-test-matrix.md)，作为 Development Readiness“第一版必须实现”需求到正向、拒绝、自动化与线上证据的测试案例覆盖入口。
- 新增 [需求测试、AI 工作流与宣传页收口设计](superpowers/specs/2026-07-10-requirements-workflow-and-landing-closure-design.md)：第一版后续工作按需求到测试矩阵、Customer Admin 首次模拟咨询与业务化决策回放、公开页“流程故事”真实产品证明、桌面/移动验收和 GitOps 线上闭环推进；现有 LangGraph 条件分支、checkpointer、auto reply 与 X6 回放未提交改动纳入同一实现范围。

### 2026-07-09

- ACS 决策编排实现补齐到 LangGraph 条件边执行：`context_gate` / `action_gate` 现在按真实分支跳转，未走节点在 `trace.graph.nodes[]` 标记 `skipped`；安全且命中审核知识的低风险回复可经 `policy_gate` 输出 `auto_reply`；进程内 native checkpointer 写入诊断用 `trace.langgraph_checkpoint_id`，补上下文完成后的持久化状态重算 trace 标记 `resumed_from_checkpoint=true`。

### 2026-06-30

- ACS 决策编排第一版接入 LangGraph 运行回放契约：`trace.steps` 继续保留线性节点记录，新增 `trace.graph.nodes[]` / `trace.graph.edges[]` 供 Customer Admin 本店铺脱敏回放和 System Admin 跨租户排障回放使用；`decision_id` 仍映射 `thread_id`，checkpoint 继续复用 `decision_graph_checkpoint`。

### 2026-06-29

- Customer Admin 登录页的外部入口改为 open_erp_agent 微信授权桥接：用户先在 `www.fcihome.com/ai-cs/customer-admin-login` 完成 open_erp_agent 微信登录和店铺校验，再由 open_erp_agent 服务端签发一次性短期 launch ticket 进入 Customer Admin；仍禁止共享 Cookie、微信/PDD session、open_erp SQLite 或外部系统登录态。

### 2026-06-26

- Customer Admin 消息历史 UI 调整为会话工作台：左侧会话搜索列表，右侧聊天时间线和模拟咨询；主界面不做“全部 / 待回复 / 买家 / 含订单 / 本地历史”筛选，也不展示已读 / 状态标签，决策状态保留在决策路径详情中用于排障。

### 2026-06-25

- 新增 open_erp integration / Customer Admin launch exchange 错误编号文档 `docs/error-codes.md`；相关响应在保留 `error.code` 的同时增加 `errorId`，便于 open_erp_agent 客户端截图排障。
- open_erp 授权桥接补充店铺展示字段：provision/admin launch ticket 可透传 `external_store_name`，Customer Admin 兑换 launch 后应把店铺下拉展示为“平台-店铺-编号”；消息历史仍只来自 Agent 决策库，connector token 失效需由外部系统刷新后新消息才会入库。
- 新增 open_erp_agent 到 Customer Admin 的受控授权桥接：open_erp 只能通过服务间接口签发一次性短期启动票据，Customer Admin 兑换后建立 Agent 自有 `agent_admin_session`；仍禁止共享 Cookie、微信/PDD session、open_erp SQLite 或外部系统登录态。
- Customer Admin 第一版新增“消息历史”和“模拟咨询”：消息历史来自 Agent 决策库，展示客户消息、AI 回复、人工回复和 `trace.steps`；模拟咨询创建 `source=simulation` 决策记录但不得发送给真实买家。

### 2026-06-24

- 发布链路门禁收紧：release gate 在 Helm reconcile 前校验 `ecommerce-cs-agent-runtime` key contract，缺 `OPEN_ERP_INTEGRATION_TOKEN` / `OPEN_ERP_BILLING_LEASE_SECRET` 等 key 直接失败；Flux / Helm / image tag / rollout / migration 任一步失败时采集 HelmRelease conditions、events 和 Pod 日志摘要后停止，不再对旧版本跑 health / live eval。
- HelmRelease 已失败或回滚时，release gate 会对新 GitOps commit 执行一次受控 `resetAt` + `requestedAt`；Admin 镜像发布前在 PR checks 和 `Publish Images` verify job 中对构建后的 Nginx 镜像运行 `nginx -t`。
- open_erp provisioning 与 `billing_lease` 在 production 环境必须显式配置 `OPEN_ERP_INTEGRATION_TOKEN` 和 `OPEN_ERP_BILLING_LEASE_SECRET`；缺失时 API 启动需 fail fast，不能退回测试默认值。
- 新增 `open_erp_agent` 无感开通第一阶段接入契约：`/v1/integrations/open-erp/provision` 幂等 provision Agent 内部 tenant/store/platform_account/connector 映射，Connector Token 明文只在首次创建或轮换时返回，服务端只保存 hash/prefix。
- `POST /v1/reply-decisions` 支持 Connector Token 鉴权时必须校验 `billing_lease`；lease 由外部计费权威签发并绑定 connector、reservation、request、platform、external_store_id 和 `feature=ai_cs.reply_decision`，缺失、过期、签名或 scope 不匹配时拒绝且不生成决策。
- 边界不变：第一阶段不做 SSO，不共享 Cookie/session，不把 ERP 微信登录或 client token 当作 Customer Admin 身份；open_erp 只是一个外部集成示例和计费权威，Agent 仍使用自有 Admin、tenant/store 和角色模型。

### 2026-06-23

- Customer Admin 登录页新增 Fcihome Account OIDC 入口：邮箱密码登录继续保留且不展示组织 ID；OIDC 仅确认身份，已绑定 `fcihome_account_sub` 可登录，唯一 active 邮箱匹配时才自动绑定并写审计；System Admin 第一版不接 OIDC，Cookie/session 继续隔离。
- Customer Admin 商品资料页收敛为商品主数据列表 + “上传商品”导入草稿：客户 UI 不再展示组织上下文、顶部刷新按钮或账号 badge；上传文件先生成 AI 抽取草稿，用户确认后才写入正式商品和资料资产。
- Product Content API 新增 `GET /v1/product-content/products`、`POST /v1/product-content/product-import-drafts`、`POST /v1/product-content/product-import-drafts/{draft_id}/confirm`；导入草稿持久化到 `product_import_draft`，审计不得记录上传正文或 `content_base64` 明文。

### 2026-06-22

- 确认 PN-04 统一门户阶段路线：`www.fcihome.com` 作为统一产品入口和品牌叙事层，先做入口、租户/店铺/listing 映射和 REST 接入契约；第一阶段不做 SSO，不共享 Cookie/session，不把 `open_erp_agent` 或微信登录作为 AI 客服默认身份源。
- Customer Admin 登录入口收敛为邮箱 + 密码：登录页和 `AdminLoginRequest` 不再展示或接收 `organization_id`；登录成功后通过 `GET /v1/admin/auth/me` 返回的可访问上下文选择店铺。
- P4 统一门户接入契约收敛：外部请求以 `platform`、`external_store_id` / `platform_account_ref`、`listing_ref`、`external_product_id`、`external_sku_id` 定位业务上下文；服务端将 API Key / Connector 和业务引用映射到内部租户、店铺、平台账号、销售实例和商品主数据。
- 补充商品主数据与销售实例边界：通用商品资料归属 `product_master`，平台 / 店铺 / 链接 / SKU 售卖上下文归属 `listing`；缺商品、SKU、订单或物流上下文时继续返回 `context_requests[]`，不能让模型猜测。
- 补充 `system-admin.ecommerce-cs-agent-dev.fcihome.com` 的公网入口排障路径：系统后台域名复用 `frp-system/bpg-frpc` 的 `cs-agent-dev-http` HTTP vhost，需要同时检查 ai-agent 外层 Traefik `frps_vhost` Host rule、K3s frpc `customDomains`、Ingress host 和 TLS SAN。

### 2026-06-21

- GitHub Actions 发布、部署、PR Helm 检查和 CodeQL 失败通知升级到 Node 24 运行时对应的 action 版本，不再依赖触发 Node.js 20 deprecation warning 的旧 action 主版本。
- 更新客户公开首页方向：`admin.ecommerce-cs-agent-dev.fcihome.com` 的 `/` 是公开宣传页和客户登录入口，对外统一使用“AI / AI 客服”白话叙事，不把 Agent 概念、系统后台入口或 ERP 身份源暴露给客户。
- 公开首页首屏、产品演示轮播和“怎么工作”动效围绕“商品信息管好了，AI 客服才答得准。”以及“上传商品说明书 → AI 学习 → 模拟问答 → AI 自动回复”主流程实现；客户 Admin 登录后仍保持 IBM / Carbon 式密集企业控制台。

### 2026-06-19

- 新增 [Admin Web UI/UX 审计与整改拆分](admin-ui-ux-audit.md)：基于 Chrome live 登录检查 customer/system Admin 的桌面与移动页面，记录 P0/P1/P2 UI/UX 问题，并拆分为可分发给开发线程的整改 prompts。

### 2026-06-18

- `AGENTS.md` 增补 Admin Web live host、Customer/System auth 边界、FRP/TLS 排查顺序、UI/UX 审计视口和 Admin 登录测试凭据 / storageState 安全规则，作为后续开发线程的项目级操作约束。
- 新增 [Admin Web UI/UX 审计与整改计划](admin-web-ui-ux-audit.md)，记录客户 Admin / 系统 Admin live 未登录页的桌面与移动端审计结论、登录信息安全边界、整改优先级和可分发给 Codex 开发线程的 prompts。
- 复验 dev 公开入口：`system-admin.ecommerce-cs-agent-dev.fcihome.com` 已解析到 `47.113.204.168`，HTTPS 证书 SAN 已覆盖 API / Customer Admin / System Admin，`/health` 返回 `200 ok`；Playwright 运行时验证 customer host 只请求 `/v1/admin/auth/me`，system host 只请求 `/v1/system-admin/auth/me`。
- 外层 ai-agent Traefik / frps 已追加 system-admin Host 并重启生效；K3s 侧继续复用 `frp-system/bpg-frpc` 的 `cs-agent-dev-http` proxy，不新增 frpc，也不配置 `type=https`。

- 实现客户后台 / 系统后台拆站基础：Admin Web 按 Host 固定 customer / system 模式，不再提供站内后台类型切换；客户 host 只刷新 `/v1/admin/auth/me`，系统 host 只刷新 `/v1/system-admin/auth/me`。
- Helm chart / dev values 已显式表达 `admin.ecommerce-cs-agent-dev.fcihome.com` 和 `system-admin.ecommerce-cs-agent-dev.fcihome.com`，Admin Ingress 同一 TLS secret 下渲染两个 host；release gate 报告拆分 API、Customer Admin、System Admin 三路 health。

- 固定客户后台和系统后台的 Web 站点边界：客户后台使用 `admin.ecommerce-cs-agent-dev.fcihome.com`，系统后台使用 `system-admin.ecommerce-cs-agent-dev.fcihome.com` 作为目标域名，`ops-admin.ecommerce-cs-agent-dev.fcihome.com` 仅作为可选别名。
- 两个后台必须使用不同登录页、Cookie / session 名、路由守卫和 API 鉴权域；客户后台 UI 不展示“系统后台”入口，系统后台不得伪装客户用户调用客户 Admin API。
- 新增本文作为开发和文档新会话的第一交接入口，并在 [AGENTS](../AGENTS.md)、[README](../README.md) 和 [Development Readiness](development-readiness.md) 建立入口。

## 新会话优先阅读顺序

1. [AGENTS](../AGENTS.md)：项目级规则、架构文档维护要求、安全边界和提交前检查。
2. [Development Handoff](development-handoff.md)：最近影响开发的文档更新和交接提示。
3. [Development Readiness](development-readiness.md)：第一版必须实现、暂不实现、验收命令和 API 覆盖状态。
4. [Implementation Plan](implementation-plan.md)：从工程骨架、数据库、鉴权、API、Admin、测试到部署的实现顺序。
5. [OpenAPI Contract](openapi.yaml)：机器可读 API 契约、schema、错误码、权限和分页口径。
6. [Testing](testing.md)、[CI/CD](ci-cd.md)、[Deployment](deployment.md)、[Deployment Artifacts](deployment-artifacts.md)、[Runbook](runbook.md)：测试、发布、部署工件和排障入口。

## 开发新线程启动提示

可复制给新的开发会话：

```text
请先读取 AGENTS.md、docs/development-handoff.md、docs/development-readiness.md、docs/implementation-plan.md 和 docs/openapi.yaml。以 handoff 和 readiness 作为当前开发入口，不重新展开架构争论；按第一版必须实现范围推进，并保持客户后台和系统后台的 Web 站点、登录页、Cookie/session、路由守卫、API 鉴权域完全隔离。若修改影响开发范围、API、部署、测试、后台边界或安全规则的文档，完成后在 docs/development-handoff.md 顶部追加一条简短记录。
```

## 维护规则

- 只记录影响开发定位、实现范围、API 契约、部署验收、测试门禁、后台边界或安全规则的文档变化。
- 不记录纯格式调整、错别字修复或不影响实现的措辞优化。
- 新记录追加在“最近文档更新”顶部，使用日期标题和 1-3 条短 bullet。
- 不写真实 token、Secret、客户数据、生产 payload 或完整 Authorization header。
