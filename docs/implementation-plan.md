# 第一版实现路线图

本文是第一版从文档进入工程实现的顺序文档，用来说明先做什么、后做什么、每个阶段交付哪些可验收产物。它不替代 [OpenAPI Contract](openapi.yaml)、[HTTP API Design](http-api-design.md)、[System Architecture](system-architecture.md)、[System Architecture HTML](system-architecture.html)、[Development Readiness](development-readiness.md)、[Deployment](deployment.md) 或后续 [Testing](testing.md)。

如果本文与接口、架构、部署或测试文档冲突，以对应来源文档为准，并同步更新本文的阶段口径。实现阶段应保持 k8s 无状态服务边界：API、Admin Web 和后台服务不依赖 Pod 本地状态；session、checkpoint、审计、业务数据和对象资料必须落 PostgreSQL、对象存储或后续明确引入的外部持久化组件。

## 第一版边界

第一版目标是形成可部署、可鉴权、可追踪、可评测的同步客服决策闭环：

- 外部系统通过 `POST /v1/reply-decisions` 提交最小问答请求。
- 服务端生成稳定 `decision_id`，处理幂等、租户边界、规则闸门 stub 和 trace。
- 缺少商品、订单、物流、规则或动作执行结果时，使用 typed context refill 和 `actions/results` 聚合。
- 客户 Admin 维护租户自己的组织、店铺、用户、审计和商品资料。
- 系统 Admin 管理平台级租户开通、上线检查、决策追踪、任务、审计和健康状态。
- eval gate、OpenAPI 校验、CI 和部署健康检查形成发布闭环。

第一版不实现以下业务能力，只保留契约、字段、路由占位或后续扩展边界：

| 暂不实现 | 第一版处理方式 |
| --- | --- |
| Connector 主动查询平台数据 | 保留 Connector / capability 契约；实际上下文由外部系统按 `context_requests[]` 回填。 |
| Webhook 订阅和投递 | 保留 OpenAPI 契约和签名字段；不实现真实投递、重试和死信处理。 |
| 异步队列和后台消息消费 | 保留 `task_id`、任务状态和 trace 引用；第一版同步 HTTP 优先。 |
| 规则灰度业务逻辑 | 保留 rule-set、dry-run、release、rollback 的契约；第一版只实现确定性规则闸门 stub 和审计边界。 |

## 1. 工程骨架与依赖入口

本阶段先让仓库重新具备可安装、可启动、可测试的最小后端工程骨架。

| 项目 | 内容 |
| --- | --- |
| 输入文档 | [Development Readiness](development-readiness.md)、[Application Technology Architecture](application-technology-architecture.md)、[Deployment](deployment.md) |
| 主要产出 | `pyproject.toml` 或 `requirements*.txt`；`ecommerce_cs_agent` 源码包；FastAPI app factory；`/health`；配置加载模块；结构化日志入口；测试依赖入口。 |
| 验收命令 / 口径 | 本地能安装依赖、导入包、启动 API，并用测试环境配置访问 `/health`；配置加载不得打印 `.env` 或 secret 明文。 |

建议最小包结构：

```text
ecommerce_cs_agent/
  api/
  core/
  db/
  domain/
  repositories/
  services/
  schemas/
```

建议验收命令：

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/unit tests/api -q
uvicorn ecommerce_cs_agent.api.app:app --host 127.0.0.1 --port 8000
curl -fsS http://127.0.0.1:8000/health
```

验收口径：

- `/health` 返回服务名、环境和 `ok` 状态，不依赖数据库即可用于容器存活检查。
- 非测试环境缺少必需配置时应 fail fast，但错误信息只能说明缺少哪个 key，不能输出 secret 值。
- 后续阶段新增模块必须通过统一配置和日志入口接入，避免散落读取环境变量。

## 2. 数据库迁移与连接

本阶段建立第一版持久化底座，先覆盖同步决策、Admin session、trace、审计和商品资料的最小表集。

| 项目 | 内容 |
| --- | --- |
| 输入文档 | [System Architecture](system-architecture.md)、[OpenAPI Contract](openapi.yaml)、[Deployment](deployment.md) |
| 主要产出 | 数据库连接池；`schema_migration`；幂等迁移 runner；`pgcrypto` 和 `vector` 扩展启用；核心表最小集；迁移测试。 |
| 验收命令 / 口径 | 迁移可重复执行；迁移版本写入 `schema_migration`；核心扩展存在；测试库和 dev PostgreSQL 都能通过同一迁移入口。 |

核心表最小集应覆盖：

| 分组 | 最小表 |
| --- | --- |
| 租户与店铺 | `organization`、`store`、`platform_account` |
| 鉴权与会话 | `external_api_token`、`admin_user`、`admin_session`、`system_admin_user`、`system_admin_session` |
| 决策与 trace | `decision_record`、`decision_trace_step`、`context_snapshot`、`decision_graph_checkpoint` |
| 动作闭环 | `action_request`、`action_result` |
| 商品资料 | `product`、`product_asset`、`product_asset_markdown`、`product_knowledge_candidate`、`product_price_snapshot` |
| 审计 | `admin_audit_log`、`system_admin_audit_log` |

建议验收命令：

```bash
python -m ecommerce_cs_agent.db.migrations --database-url "$DATABASE_URL" --dry-run
python -m ecommerce_cs_agent.db.migrations --database-url "$DATABASE_URL" up
python -m pytest tests/db -q
psql "$DATABASE_URL" -c "select extname from pg_extension where extname in ('pgcrypto', 'vector') order by extname;"
psql "$DATABASE_URL" -c "select version, applied_at from schema_migration order by version;"
```

验收口径：

- `schema_migration` 使用唯一版本号和应用时间，重复执行不重复写入同一版本。
- `request_id`、`decision_id`、`context_request_id`、`action_id` 等幂等键具备数据库唯一约束。
- JSONB raw payload 可保存原始外部上下文，但默认查询和日志只使用脱敏摘要。

## 3. 鉴权与租户边界

本阶段先把三类身份边界做硬隔离：外部 API token、客户 Admin session、系统 Admin session。

| 项目 | 内容 |
| --- | --- |
| 输入文档 | [HTTP API Design](http-api-design.md)、[Customer Admin Design](customer-admin-design.md)、[System Admin Design](system-admin-design.md)、[OpenAPI Contract](openapi.yaml) |
| 主要产出 | 外部 API Bearer token 校验；客户 Admin HttpOnly session；系统 Admin HttpOnly session；组织 / 店铺 / 角色鉴权依赖；token hash 存储；审计入口。 |
| 验收命令 / 口径 | 三类凭据不能跨 API 分组使用；跨组织、跨店铺访问默认拒绝；所有后台写操作都能记录操作者和租户上下文。 |

鉴权边界：

| 凭据类型 | 允许访问 | 必须拒绝 |
| --- | --- | --- |
| 外部 API token | `/v1/reply-decisions`、typed context refill、`actions/results`、人工反馈、按契约允许的 trace 查询 | `/v1/admin/*`、`/v1/system-admin/*` |
| 客户 Admin session | `/v1/admin/*`、`/v1/product-content/*`、本租户授权店铺的审计和 trace | `/v1/system-admin/*`、其他组织或未授权店铺 |
| 系统 Admin session | `/v1/system-admin/*`、跨租户 readiness 和排障视图 | 客户业务写入，除非通过明确的代运营接口并写系统审计 |

建议验收命令：

```bash
python -m pytest tests/unit/test_auth.py tests/contract/test_auth_boundaries.py -q
curl -i -H "Authorization: Bearer <external-api-token>" http://127.0.0.1:8000/v1/admin/auth/me
curl -i -b "<customer-admin-cookie>" http://127.0.0.1:8000/v1/system-admin/health
```

验收口径：

- 第一条 `curl` 应返回 `401` 或 `403`，不能泄露 Admin 用户信息。
- 第二条 `curl` 应返回 `401` 或 `403`，不能把客户后台 session 当作系统后台 session。
- token、session secret、密码 hash、cookie 原文不得出现在日志、trace、API 响应或测试快照中。

## 4. `reply-decisions` 主链路

本阶段落地第一版同步客服决策入口。实现重点是稳定协议、幂等、追踪和可回放，不追求一次性完成复杂 Agent 智能。

| 项目 | 内容 |
| --- | --- |
| 输入文档 | [OpenAPI Contract](openapi.yaml)、[HTTP API Design](http-api-design.md)、[System Architecture](system-architecture.md)、[Development Readiness](development-readiness.md) |
| 主要产出 | `POST /v1/reply-decisions`；请求 / 响应 schema；`request_id` 幂等；`decision_id` 生成；`decision_record` 写入；规则闸门 stub；trace step 记录；基础错误模型。 |
| 验收命令 / 口径 | 最小请求可返回稳定结构；重复 `request_id` 返回同一决策或明确幂等结果；所有响应包含 `decision_id`；高风险或上下文不足默认不自动回复。 |

第一版规则闸门 stub 口径：

- 缺少关键上下文时返回 `context_request` 或 `candidate`。
- 识别到退款、赔付、投诉、处罚、辱骂等高风险信号时返回 `handoff` 或 `candidate`。
- `auto_reply` 必须经过明确白名单条件、低风险判断和可解释 trace；模型生成内容本身不能直接放行。

建议验收命令：

```bash
python -m pytest tests/contract/test_reply_decisions.py tests/integration/test_reply_decision_flow.py -q
python -m evals.cli run-suite --suite quick --target mock
curl -fsS -X POST http://127.0.0.1:8000/v1/reply-decisions \
  -H "Authorization: Bearer <external-api-token>" \
  -H "Content-Type: application/json" \
  --data @tests/fixtures/reply_decisions/minimal_request.json
```

验收口径：

- 响应字段与 `docs/openapi.yaml` 一致。
- `decision_record` 可以通过 `decision_id` 查到租户、店铺、外部消息引用、决策状态、风险等级和 trace 摘要。
- 同一租户、店铺、`request_id` 重试不会生成多条互相冲突的决策。

## 5. typed context refill 与 `actions/results`

本阶段把主链路补齐为可多步推进的同步闭环：缺上下文时请求回填，动作执行后等待结果。

| 项目 | 内容 |
| --- | --- |
| 输入文档 | [OpenAPI Contract](openapi.yaml)、[HTTP API Design](http-api-design.md)、[System Architecture](system-architecture.md) |
| 主要产出 | `contexts/products`、`contexts/orders`、`contexts/logistics`、`contexts/rules`；`actions/results`；上下文快照聚合；动作结果聚合；幂等键；trace 更新。 |
| 验收命令 / 口径 | 外部系统可按 `context_requests[]` 并行回填；服务端按同一个 `decision_id` 聚合；动作结果未成功前不能向买家确认业务已完成。 |

实现口径：

- products、orders、logistics、rules 统一保存为 typed snapshot，保留 `business_updated_at`、`captured_at`、`source` 和 raw payload 引用。
- 聚合上下文时遵循最近有效快照原则，旧快照不删除，用于回放和审计。
- `action_result.status=success` 之前，Agent 只能给候选、等待或转人工，不能确认退款、改地址、取消订单等真实动作成功。

建议验收命令：

```bash
python -m pytest tests/contract/test_context_refill.py tests/contract/test_action_results.py -q
python -m pytest tests/integration/test_reply_decision_context_resume.py -q
```

验收口径：

- 每个 context refill endpoint 都校验租户、店铺、`decision_id` 和 `context_request_id`。
- 重复回填同一 `context_request_id` 不生成重复有效快照。
- trace 中能看到主请求、缺口判断、回填接收、聚合、动作等待和结果处理步骤。

## 6. 客户 Admin

本阶段实现客户可登录后台的第一版 API 能力，重点是客户自己维护业务资料和查看本租户审计。

| 项目 | 内容 |
| --- | --- |
| 输入文档 | [Customer Admin Design](customer-admin-design.md)、[HTTP API Design](http-api-design.md)、[OpenAPI Contract](openapi.yaml)、[Development Readiness](development-readiness.md) |
| 主要产出 | `/v1/admin/auth/me`；organizations；stores；users；audit；product-content 入口；客户 session 校验；角色权限；客户审计日志。 |
| 验收命令 / 口径 | 登录态可读取当前用户、组织、店铺和角色；客户只能操作授权组织 / 店铺；写操作写入 `admin_audit_log`。 |

第一版接口分组：

| 分组 | 实现内容 |
| --- | --- |
| auth/me | 当前用户、组织、店铺、角色、权限摘要和 session 状态。 |
| organizations | 当前用户可访问组织列表和默认组织选择。 |
| stores | 当前组织下可访问店铺列表、店铺设置摘要和启用状态。 |
| users | 成员列表、邀请、角色调整和禁用。 |
| audit | 客户后台配置变更、知识审核、规则变更和敏感操作查询。 |
| product-content | 商品、SKU、资料资产、Markdown 审稿稿件、知识候选、价格快照和资料健康检查的入口。 |

建议验收命令：

```bash
python -m pytest tests/contract/test_customer_admin.py tests/integration/test_customer_admin_tenant_scope.py -q
```

验收口径：

- `GET /v1/admin/auth/me` 必须返回前端渲染所需的最小身份上下文。
- 客户 Admin session 不能访问系统 Admin API。
- 每个写接口都记录操作者、组织、店铺、对象类型、对象 ID、动作和差异摘要。

## 7. 系统 Admin

本阶段实现平台内部人员使用的系统后台 API，和客户 Admin 彻底隔离。

| 项目 | 内容 |
| --- | --- |
| 输入文档 | [System Admin Design](system-admin-design.md)、[System Admin UI Prototype](system-admin-ui-prototype.html)、[OpenAPI Contract](openapi.yaml)、[Deployment](deployment.md) |
| 主要产出 | tenant；store；readiness；message-traces；tasks；audit；health；系统 Admin session；跨租户访问审计；脱敏视图。 |
| 验收命令 / 口径 | 系统后台可开通和查看租户 / 店铺；可查询 readiness、trace、任务和系统健康；跨租户数据访问写系统审计。 |

第一版接口分组：

| 分组 | 实现内容 |
| --- | --- |
| tenant / store | 组织和店铺创建、启停、平台绑定、初始客户管理员开通。 |
| readiness | 商品资料、知识审核、规则、动作能力、价格快照、API token、health 的上线检查。 |
| message-traces | 按 `decision_id`、请求 ID、外部消息 ID、租户、店铺、平台和时间查询决策链路。 |
| tasks | 资料解析、Markdown 转换、知识抽取、embedding、评测运行等任务状态查询契约。 |
| audit | 系统后台登录、权限变更、跨租户查看、代运营修改和敏感数据访问审计。 |
| health | API、PostgreSQL、pgvector、对象存储、LLM provider、Admin Web 和部署版本状态。 |

建议验收命令：

```bash
python -m pytest tests/contract/test_system_admin.py tests/integration/test_system_admin_scope.py -q
```

验收口径：

- 系统后台账号、角色和 session 与客户后台完全隔离。
- 默认返回脱敏 trace；完整 raw payload 只允许高权限排障接口访问，并必须记录审计。
- readiness 能给出明确阻断项，例如缺资料、知识未审核、价格过期、规则未启用、动作能力异常或 health 失败。

## 8. 商品资料与知识审核

本阶段把 Agent 长期依赖的商品资料、Markdown 审稿、知识候选和价格快照落为可维护的数据闭环。

| 项目 | 内容 |
| --- | --- |
| 输入文档 | [Customer Admin Design](customer-admin-design.md)、[System Architecture](system-architecture.md)、[OpenAPI Contract](openapi.yaml)、[Development Readiness](development-readiness.md) |
| 主要产出 | asset 归档；Markdown 审稿稿件；candidate review；price snapshot；product health；对象存储适配；知识审核审计。 |
| 验收命令 / 口径 | 原始资料可归档；Markdown 只作为审稿稿件；候选知识必须审核后才进入可召回知识；价格缺失、过期或冲突时不能自动报价。 |

实现口径：

- `product_asset` 保存原始文件元数据、对象存储引用、hash、版本、适用商品 / SKU 和上传人。
- `product_asset_markdown` 保存可审阅稿件，不直接作为自动回复知识源。
- `product_knowledge_candidate` 经过批准、拒绝、改写、脱敏和适用范围标注后，才进入 `knowledge_entry` 或后续等价知识表。
- `product_price_snapshot` 记录来源、生效时间、失效时间、活动价、币种和冲突状态。
- product health 汇总资料缺口、解析失败、待审核、价格过期、知识覆盖不足和冲突项。

建议验收命令：

```bash
python -m pytest tests/contract/test_product_content.py tests/integration/test_product_content_review.py -q
python -m pytest tests/integration/test_product_health.py -q
```

验收口径：

- 未审核候选知识不会被 retrieval 使用。
- 价格快照过期或冲突时，`reply-decisions` 返回候选、补上下文或转人工，不返回自动报价。
- 原始资料、Markdown 稿件、候选审核和最终知识之间有可追踪引用链。

## 9. eval gate 与 CI

本阶段把“能跑”和“能发布”之间的质量门禁补齐，避免只靠人工试接口判断是否可上线。

| 项目 | 内容 |
| --- | --- |
| 输入文档 | [Development Readiness](development-readiness.md)、[Testing](testing.md)、[OpenAPI Contract](openapi.yaml)、[Deployment](deployment.md)、[Automated Blind Testing Design](superpowers/specs/2026-06-14-automated-blind-testing-design.md) |
| 主要产出 | unit / contract / integration / eval 测试分层；OpenAPI 校验；mock eval；live eval；GitHub Actions CI；CodeQL 与测试结果汇总。 |
| 验收命令 / 口径 | PR 必须跑确定性测试和 OpenAPI 校验；main 或发布前跑 live eval；失败用例能追踪到 `decision_id`、输入、trace 和评分理由。 |

测试分层：

| 层级 | 覆盖内容 |
| --- | --- |
| unit | 配置、鉴权、规则闸门、幂等、最近有效上下文选择、资料健康计算。 |
| contract | OpenAPI 请求 / 响应、权限边界、错误模型、Admin API、typed context refill、actions/results。 |
| integration | PostgreSQL 迁移、决策主链路、上下文回填、客户 Admin、系统 Admin、商品知识审核。 |
| eval | mock quick suite、live quick suite、红线用例、失败沉淀回归。 |

建议验收命令：

```bash
python -m pytest tests/unit tests/contract tests/integration --maxfail=1
python -m evals.cli run-suite --suite quick --target mock
ruby -e "require 'yaml'; YAML.load_file('docs/openapi.yaml'); puts 'openapi yaml ok'"
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com AGENT_API_TOKEN=<from-secret> python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

验收口径：

- OpenAPI schema 是 contract tests 的来源之一，不能让实现接口和 `docs/openapi.yaml` 漂移。
- live eval 从运行时 Secret 读取 token，不把 token 写入仓库、文档、日志或 CI 输出。
- CI 失败时能区分 CodeQL、安全门禁、单元测试、契约测试、集成测试和 eval 失败。

## 10. 部署闭环

本阶段打通镜像、GitOps tag、迁移、健康检查和 live eval，形成从提交到 dev 环境验证的完整闭环。

| 项目 | 内容 |
| --- | --- |
| 输入文档 | [Deployment](deployment.md)、[Development Readiness](development-readiness.md)、[Testing](testing.md)、[OpenAPI Contract](openapi.yaml) |
| 主要产出 | API / Admin 镜像；Dockerfile；Helm chart 或现有 GitOps 更新入口；migration job；image tag 更新流程；health probes；发布后 live eval。 |
| 验收命令 / 口径 | 镜像可构建和推送；GitOps 使用明确 tag 部署；迁移先于应用流量；API/Admin `/health` 通过；live eval 通过后才认为 dev 部署完成。 |

建议部署顺序：

1. CI 构建 API / Admin 镜像并推送 registry。
2. 生成不可变 image tag，例如 `dev-YYYYMMDD-HHMM-<sha>`。
3. 更新 GitOps values 中的 API / Admin tag。
4. Kubernetes 执行 migration job。
5. API / Admin deployment 滚动更新。
6. 验证 health、ingress、数据库扩展、核心 API 和 live eval。

建议验收命令：

```bash
docker build -f deploy/docker/api.Dockerfile -t registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-api:<tag> .
docker build -f deploy/docker/admin.Dockerfile -t registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-admin:<tag> .
helm lint deploy/helm/ecommerce-cs-agent -f deploy/helm/ecommerce-cs-agent/values-dev.yaml
helm template ecommerce-cs-agent deploy/helm/ecommerce-cs-agent -f deploy/helm/ecommerce-cs-agent/values-dev.yaml
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get pods,svc,ingress
curl -fsS https://api.ecommerce-cs-agent-dev.fcihome.com/health
curl -fsS https://admin.ecommerce-cs-agent-dev.fcihome.com/health
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com AGENT_API_TOKEN=<from-secret> python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

验收口径：

- GitOps 中只记录镜像 tag、Secret key 名称、namespace 和非敏感配置，不提交真实 secret。
- `readiness` 失败、迁移失败、health 失败或 live eval 失败时，不把该 tag 标记为可发布。
- 发布记录应能关联 commit、image tag、migration version、OpenAPI version、eval report 和关键 `decision_id` 样例。
