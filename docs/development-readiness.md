# 开发就绪说明

本文集中说明第一版开发边界、暂不实现内容、验收命令和 API 覆盖状态。它不是新的架构来源，只汇总当前仓库已有设计文档，便于进入实现阶段时统一范围和检查口径。

相关来源：

- [README](../README.md)：项目目标、核心设计原则和文档入口。
- [HTTP API Design](http-api-design.md)：外部系统接入、补上下文、动作结果、反馈、Admin API 和安全兼容性要求。
- [OpenAPI Contract](openapi.yaml)：第一版主链路、客户 Admin、系统 Admin 和商品资料接口的机器可读契约。
- [System Architecture](system-architecture.md)：系统组件、数据流、数据库模型、决策机制和第一版实现边界。
- [Application Technology Architecture](application-technology-architecture.md)：技术栈、前后台边界、HTTP 接入协议、k8s 无状态部署原则。
- [Customer Admin Design](customer-admin-design.md)：客户后台定位、权限、商品资料、知识审核、规则、动作能力和审计。
- [System Admin Design](system-admin-design.md)：系统后台目标、接口分组、上线检查、排障、安全治理和验收口径。
- [Deployment](deployment.md)：dev 环境、运行时配置、部署验收和仍缺工程化内容。
- [Development Setup](development-setup.md)：本地 Python 环境、依赖入口、eval 命令、环境变量和 `.env` 规则。
- [Implementation Plan](implementation-plan.md)：第一版从工程骨架到部署闭环的实现顺序。
- [Database Migrations](database-migrations.md)：迁移命名、`schema_migration`、扩展初始化、环境执行和回滚口径。
- [Testing](testing.md)：当前可运行测试、测试分层、OpenAPI contract test、mock/live eval 和门禁。
- [CI/CD](ci-cd.md)：PR checks、CodeQL、OpenAPI 校验、镜像构建、Registry 推送、GitOps 和 release gate。
- [Deployment Artifacts](deployment-artifacts.md)：应用仓库、GitOps / Flux / Helm 仓库和运行时集群的职责边界。
- [Runbook](runbook.md)：`/health`、live eval、HTTP 状态、DB、LLM、K8s rollout 和日志脱敏排障。
- [Security Local Files](security-local-files.md)：本地敏感文件、生成物、提交前检查和误加入 Secret 的处理。
- [Automated Blind Testing Design](superpowers/specs/2026-06-14-automated-blind-testing-design.md)：本地快测、PR 门禁、盲测和发布门禁。

## 1. 第一版必须实现

第一版目标是先形成“外部系统接入 Agent 决策服务”的可控闭环，而不是一次性替代客服系统。

| 范围 | 第一版必须具备 | 依据 |
| --- | --- | --- |
| 外部接入 | 外部客服系统调用 `POST /v1/reply-decisions`，提交买家消息、最小会话、租户、店铺、平台和可选上下文。 | [HTTP API Design](http-api-design.md)、[System Architecture](system-architecture.md) |
| 决策输出 | 返回 `auto_reply`、`candidate`、`handoff`、`context_request` 或 `action_request`，并带 `decision_id`、风险、原因和 trace。 | [HTTP API Design](http-api-design.md) |
| typed context refill | 支持按 `context_requests[]` 回填商品、订单、物流和规则上下文，并用同一个 `decision_id` 聚合。 | [HTTP API Design](http-api-design.md)、[System Architecture](system-architecture.md) |
| 动作闭环 | 动作类需求返回结构化 `action_request`；外部系统执行真实业务 API 后调用 `actions/results` 回传结果。 | [HTTP API Design](http-api-design.md)、[Application Technology Architecture](application-technology-architecture.md) |
| 人工反馈 | 人工客服处理后调用 `POST /v1/feedback/human-replies`，沉淀采用率、修改幅度、处理结果和知识候选来源。 | [System Architecture](system-architecture.md)、[Automated Blind Testing Design](superpowers/specs/2026-06-14-automated-blind-testing-design.md) |
| 决策编排 | 内部使用 LangGraph StateGraph 或等价状态机表达补上下文等待、动作结果等待、规则闸门、人工介入和节点级 trace。 | [System Architecture](system-architecture.md)、[Application Technology Architecture](application-technology-architecture.md) |
| 持久化 | PostgreSQL + JSONB + pgvector 保存租户、店铺、商品资料、会话、消息、上下文快照、决策、checkpoint、反馈、知识和向量。 | [System Architecture](system-architecture.md)、[Application Technology Architecture](application-technology-architecture.md) |
| k8s 无状态 | API 容器、Admin Web/API 不保存本地业务状态；session、checkpoint、审计和业务数据落外部存储。 | [Application Technology Architecture](application-technology-architecture.md)、[Deployment](deployment.md) |
| 客户 Admin | 提供 Agent 自有 `/`、`/login`、`/admin`，支持登录、组织/店铺切换、商品资料、知识审核、规则、动作能力和审计。 | [Customer Admin Design](customer-admin-design.md)、[HTTP API Design](http-api-design.md) |
| 系统 Admin | 支持系统管理员登录、租户/店铺开通、配置完成度、决策追踪、任务、模型用量、评测、API 凭据、安全审计和健康检查。 | [System Admin Design](system-admin-design.md) |
| 规则闸门 | 自动回复必须经过规则、风险、上下文完整性和置信度控制；高风险或上下文不足时输出候选或转人工。 | [README](../README.md)、[System Architecture](system-architecture.md) |
| 测试门禁 | 本地快测覆盖 unit / contract / policy；PR 覆盖接口契约、状态机、权限、幂等、context refill、policy gate 和 Admin 审计关键流。 | [Automated Blind Testing Design](superpowers/specs/2026-06-14-automated-blind-testing-design.md) |

## 2. 暂不实现

以下能力当前只保留字段、协议或设计扩展点，不作为第一版交付必需项：

| 暂不实现 | 原因 / 当前处理方式 | 依据 |
| --- | --- | --- |
| 多平台 Connector 主动查询 | 第一版由外部系统按 `context_requests[]` 主动回填，避免 Agent 直接登录或读取电商平台后台。 | [System Architecture](system-architecture.md)、[HTTP API Design](http-api-design.md) |
| 复杂消息队列、Webhook 订阅、死信重试 | 第一版同步 HTTP 优先；异步事件、任务队列和回调在流量或耗时上来后再引入。 | [System Architecture](system-architecture.md)、[HTTP API Design](http-api-design.md) |
| 自动训练或模型微调 | 人工回复先进入反馈和知识候选，必须经审核后进入知识库；不自动把客服回复塞进向量库。 | [System Architecture](system-architecture.md) |
| 独立数据仓库和实时 BI | 第一版先用 PostgreSQL、trace、评测报告和后台查询满足排障与上线判断。 | [System Architecture](system-architecture.md)、[System Admin Design](system-admin-design.md) |
| Redis 作为必需依赖 | dev 部署明确 Redis 暂不部署；后续需要 session cache、队列或异步任务时再引入。 | [Deployment](deployment.md) |
| 供应商锁定 SSO / MFA / 复杂审批流 | 第一版使用 Agent 自有登录和权限；企业 SSO、MFA、规则灰度、审批流后续扩展。 | [Customer Admin Design](customer-admin-design.md)、[System Admin Design](system-admin-design.md) |
| 买家会话接待界面 | 外部客服系统继续负责客服工作台、消息接收和真实发送。 | [Customer Admin Design](customer-admin-design.md)、[System Admin Design](system-admin-design.md) |
| 系统后台替客户批量审核业务知识 | 系统后台做运营、排障和治理，不默认代替客户完成知识审核。 | [System Admin Design](system-admin-design.md) |
| 大规模 LLM 盲测作为 PR 默认项 | PR 默认跑确定性自动化；盲测用于每日、发布前和失败沉淀回归。 | [Automated Blind Testing Design](superpowers/specs/2026-06-14-automated-blind-testing-design.md) |

## 3. 验收命令

### 3.1 文档完整性

新增或调整文档链接后至少检查：

```bash
test -f docs/development-readiness.md
rg -n "\\[Development Readiness\\]\\(docs/development-readiness.md\\)" README.md
```

如果修改 `docs/system-architecture.html` 中的视图、流程、节点标签、连线、数据库 schema 或详情，必须额外运行：

```bash
node docs/scripts/validate-x6-architecture-runtime.mjs
node docs/scripts/validate-business-flow-x6-labels.mjs
```

本文件只新增 Markdown 文档，不需要运行 X6 HTML 校验脚本。

### 3.2 本地开发快测

当前仓库已恢复的最小可运行测试入口：

```bash
python -m evals.cli --help
python -m unittest tests.evals.test_live_cli -v
```

后续补齐 Python 项目依赖和测试目录后，按 [Testing](testing.md) 扩展为：

```bash
pytest tests/unit tests/contract tests/policy
```

如果项目某阶段引入 Node 测试脚本，再补充对应 `npm run test:*` 命令；不要在没有脚本入口时把临时命令写成团队验收口径。

### 3.3 PR 检查

PR 阶段应运行确定性自动化，至少覆盖 API contract、状态机 / LangGraph 流程、权限、幂等、context refill、policy gate 和 Admin 审计关键流：

```bash
pytest tests/unit tests/contract tests/integration --maxfail=1
```

当前 CI/CD 状态和待补 workflow 见 [CI/CD](ci-cd.md)。在完整测试目录落地前，PR 至少应继续运行 OpenAPI 校验、CodeQL、`evals.cli` 单元测试和 `git diff --check`。


### 3.4 dev 部署验收

部署文档当前给出的 dev 环境验收命令：

```bash
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl get nodes
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get pods,svc,ingress,secrets
curl -fsS https://api.ecommerce-cs-agent-dev.fcihome.com/health
curl -fsS https://admin.ecommerce-cs-agent-dev.fcihome.com/health
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com AGENT_API_TOKEN=<from-secret> python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

`AGENT_API_TOKEN` 必须从运行时 Secret 获取，不写入代码仓库、文档或聊天记录。

### 3.5 发布前评测门禁

发布前应汇总快测、回归集、盲测核心集、红线集和基线对比。盲测失败需要沉淀为固定回归用例，并能追踪到 `decision_id`、trace、输入数据和评分理由。

## 4. API 覆盖状态

本节描述“设计文档是否已经覆盖第一版 API 范围”，不代表代码已经全部实现。实现阶段应以本表作为接口落地清单，并以 contract tests 固化。

| API / 路由 | 第一版状态 | 文档覆盖 | 备注 |
| --- | --- | --- | --- |
| `GET /` | 必须实现 | 已覆盖 | 公开宣传页和登录入口，不读取租户业务数据。 |
| `GET /login` | 必须实现 | 已覆盖 | Agent 自有登录页。 |
| `GET /admin` | 必须实现 | 已覆盖 | 受保护客户后台 shell，未登录回到 `/login`。 |
| `POST /v1/reply-decisions` | 必须实现 | 已覆盖 | 外部客服系统唯一同步问答入口。 |
| `POST /v1/reply-decisions/{decision_id}/contexts/products` | 必须实现 | 已覆盖 | 按 `context_requests[type=products]` 回填商品快照或引用。 |
| `POST /v1/reply-decisions/{decision_id}/contexts/orders` | 必须实现 | 已覆盖 | 回填订单快照。 |
| `POST /v1/reply-decisions/{decision_id}/contexts/logistics` | 必须实现 | 已覆盖 | 回填物流、仓库或发货状态。 |
| `POST /v1/reply-decisions/{decision_id}/contexts/rules` | 必须实现 | 已覆盖 | 回填店铺规则、平台规则或风控策略。 |
| `POST /v1/reply-decisions/{decision_id}/actions/results` | 必须实现 | 已覆盖 | 外部系统执行真实动作后回传结果。 |
| `POST /v1/feedback/human-replies` | 必须实现 | 已覆盖 | 回传人工最终回复、是否采用候选和处理结果。 |
| `GET /v1/message-traces/{decision_id}` | 必须实现 | 已覆盖 | 查询单条消息完整处理过程。 |
| `/v1/admin/auth/*` | 必须实现 | 已覆盖 | 客户后台登录、退出、当前用户。 |
| `/v1/admin/organizations`、`/v1/admin/stores` | 必须实现 | 已覆盖 | 客户后台组织和店铺上下文。 |
| `/v1/admin/users`、`/v1/admin/invitations`、角色变更 | 必须实现 | 已覆盖 | 客户后台用户、邀请和角色权限。 |
| `/v1/admin/audit-logs` | 必须实现 | 已覆盖 | 客户后台配置变更和敏感操作审计。 |
| `/v1/product-content/*` | 必须实现 | 已覆盖 | 商品、资料、Markdown 审稿、知识候选审核、价格快照和资料体检。 |
| `/v1/system-admin/*` | 必须实现 | 已覆盖 | 系统后台与客户后台 API 分组隔离，覆盖租户、店铺、readiness、排障、任务、评测、凭据、审计和健康。 |
| `POST /v1/events/messages` | 暂不实现 | 已覆盖 | 后续异步事件入口；使用外部 API token、`request_id` 幂等、返回 `task_id` 和可选 `decision_id`。 |
| `GET /v1/tasks/{task_id}` | 暂不实现 | 已覆盖 | 后续异步任务轮询；返回状态、失败 / 重试、trace 引用和脱敏决策摘要。 |
| `/v1/webhook-subscriptions*` | 暂不实现 | 已覆盖 | 后续 Webhook 订阅管理；覆盖签名、事件幂等、重试、死信和脱敏要求。 |
| `/v1/admin/connectors*` | 暂不实现 | 已覆盖 | 后续客户 Admin Connector 配置；第一版仍以 `context_requests[]` 回填为主。 |
| `/v1/admin/rules/rule-sets*` | 暂不实现 | 已覆盖 | 后续客户 Admin 规则版本、灰度、dry-run 和回滚；系统 Admin 保留平台级治理边界。 |

实现 API 时需要同步满足以下通用约束：

- 所有外部接口使用 `/v1` 版本前缀。
- 主请求必须支持 `request_id` 幂等，补上下文和动作结果必须支持 `context_request_id` / `action_id` 与 `idempotency_key`。
- 响应必须包含 `decision_id`，用于反馈、审计、消息追踪和问题排查。
- 外部系统 API Key / Bearer Token 不能调用客户 Admin API 或系统 Admin API。
- 客户后台 session 不能调用系统后台 API。
- 密钥、token、密码和私钥不返回明文，不写入文档、日志或前端响应。

## 5. 进入开发前检查清单

- README 已链接本文件，且 `docs/development-readiness.md` 存在。
- README 已链接 [Development Setup](development-setup.md)、[Implementation Plan](implementation-plan.md)、[Database Migrations](database-migrations.md)、[Testing](testing.md)、[CI/CD](ci-cd.md)、[Deployment Artifacts](deployment-artifacts.md)、[Runbook](runbook.md) 和 [Security Local Files](security-local-files.md)。
- 第一版实现范围和暂不实现范围已经和产品、后端、前端、部署、测试口径对齐。
- 本地开发环境、数据库迁移、测试、CI/CD、部署工件和运行排障都有执行型文档入口。
- API contract tests 覆盖主决策、补上下文、动作结果、反馈、追踪、客户 Admin 和系统 Admin 的权限边界。
- 本地快测、PR 确定性门禁、每日盲测、发布红线门禁有清晰运行入口。
- dev 部署继续遵守 k8s 无状态原则，真实 Secret 只放在 GitHub Secrets、Kubernetes Secrets 或外部 Secret Manager。
- `.gitignore` 已覆盖 `.env`、`*.env`、`.venv/`、`.pytest_cache/`、`__pycache__/`、`*.pyc`、`*.egg-info/`、`reports/evals/` 和默认不提交的本地截图。
