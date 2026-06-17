# CI/CD

本文记录 `ecommerce-cs-agent` 的当前 CI/CD 状态、目标流水线、GitHub Secrets key、PR / main / release 门禁、GitOps 发布方式和分阶段落地顺序。敏感值只记录 key，不记录明文。

相关来源：

- [Deployment](deployment.md)：dev 环境、Registry、GitOps、运行时 Secret 和部署验收。
- [Development Readiness](development-readiness.md)：第一版开发边界、验收命令和 API 覆盖状态。
- [OpenAPI Contract](openapi.yaml)：外部决策、补上下文、Admin 和系统后台 API 契约。
- [Automated Blind Testing Design](superpowers/specs/2026-06-14-automated-blind-testing-design.md)：研发快测、盲测和发布门禁设计。

## 1. 当前状态

当前仓库已有 CodeQL、PR checks、镜像发布和 dev GitOps 更新 workflow。CodeQL 负责 SAST；PR checks 负责可重复的契约 / 测试门禁；`Publish Images` 在 `main` 发布 API/Admin 镜像；`Deploy Dev GitOps` 在镜像发布成功后更新独立 GitOps 仓库的 dev values。

| 项目 | 当前状态 |
| --- | --- |
| CodeQL SAST | 已有 workflow，触发 `pull_request` 到 `main`、`push` 到 `main` 和每周定时扫描。 |
| 邮件通知 | 已有 `Notify security gate blocked` job，CodeQL 失败时使用 SMTP GitHub Secrets 发送拦截通知。 |
| Markdown / OpenAPI 校验 | 已在 `.github/workflows/pr-checks.yml` 中执行。 |
| Python tests | 已在 PR checks 和 `Publish Images` verify job 中执行。 |
| Eval CLI unit tests | 已在 PR checks 中执行。 |
| Helm lint / template | 已在 `Publish Images` verify job 中执行。 |
| API / Admin image build | 已在 `.github/workflows/publish-images.yml` 中构建。 |
| GHCR + 阿里云 Registry 推送 | 已在 `Publish Images` 中推送；阿里云凭据来自 GitHub Secrets。 |
| GitOps image tag 更新 | 已由 `.github/workflows/deploy-dev.yml` 写入 `liuyenhui/fhg-gitops-repo` dev values。 |
| K8s rollout 与 health / live eval | 由发布执行者在 Flux 同步后做上线验收并记录证据。 |

第一阶段仍不要把 build、test、push、deploy 的完成状态和 CodeQL 混在一起。CodeQL 只覆盖 SAST；应用构建、镜像发布、GitOps 更新和发布后验证保持独立 workflow 与独立证据。

## 2. 目标流水线

目标流水线按“先拦截风险，再构建发布，再由 GitOps 驱动部署，再做线上验证”的顺序落地：

```text
PR
-> CodeQL SAST
-> OpenAPI 校验
-> Python tests
-> Helm lint/template
-> build API/Admin images
-> push GHCR + 阿里云 Registry
-> GitOps image tag 更新
-> K8s rollout
-> health/live eval
```

建议拆成三类 workflow：

| Workflow | 触发 | 职责 |
| --- | --- | --- |
| `pr-checks` | `pull_request` | Markdown / OpenAPI、unit / contract / integration、eval CLI unit tests、Helm lint / template。 |
| `Publish Images` | `push` 到 `main`、`workflow_dispatch`、`codex/publish-*` | 构建 API / Admin 镜像，推送 GHCR 和阿里云 Registry。 |
| `Deploy Dev GitOps` | `Publish Images` 成功后或 `workflow_dispatch` | 更新 GitOps image tag / values，由 Flux 同步到 K8s；rollout、health 和 live eval 由发布执行者验证。 |

PR 阶段原则上不推送正式镜像、不改 GitOps 目标状态；main / release 阶段才发布镜像和触发部署。

## 3. GitHub Secrets

GitHub Secrets 只记录 key，不在仓库、文档、日志或聊天记录中保存真实值。

### 3.1 邮件通知

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `MAIL_FROM`
- `SECURITY_NOTIFY_TO`

### 3.2 Registry

- `ALIYUN_REGISTRY_USERNAME`
- `ALIYUN_REGISTRY_PASSWORD`
- `GITHUB_TOKEN` 或具备 GHCR `packages:write` 权限的 GitHub token

GHCR 默认优先使用 GitHub Actions 内置 `GITHUB_TOKEN` 和 workflow `packages: write` 权限。只有跨仓库、跨组织或权限不足时，才补充专用 token。

### 3.3 GitOps / K8s

本仓库不直接 `kubectl` 修改集群。`Deploy Dev GitOps` 使用以下 GitHub Secret 推送 GitOps 仓库的 dev values 变更：

- `GITOPS_TOKEN`
- `KUBECONFIG`

`KUBECONFIG` 只作为后续需要时的备选方案，不作为默认部署方式。默认路径通过 GitOps repo 的 tag / values 变更驱动 Flux。

## 4. PR Checks

PR 检查只运行确定性、可重复、可快速反馈的门禁。目标是阻止不满足契约、安全边界和基础质量要求的变更进入 `main`。

| 检查 | 内容 |
| --- | --- |
| Markdown | 文档链接、必要文件存在、关键命令片段可维护。 |
| OpenAPI | `docs/openapi.yaml` 结构合法、operationId 唯一、schema 引用可解析。 |
| Unit tests | 纯函数、策略、权限、配置解析、工具函数和错误处理。 |
| Contract tests | `/v1/reply-decisions`、typed context refill、动作结果、反馈、trace、客户 Admin 和系统 Admin API 契约。 |
| Integration tests | 数据库迁移、幂等、租户隔离、policy gate、Admin 审计、状态机 / LangGraph 编排。 |
| Eval CLI unit tests | `evals.cli`、case loader、runner、report、mock / live target 参数和失败退出码。 |
| Helm lint/template | Helm chart、values、Secret 引用、Ingress、Service、Deployment、migration job 渲染检查。 |

建议 PR 阶段命令逐步固定为：

```bash
python -m pytest tests/unit tests/contract tests/integration tests/evals --maxfail=1
```

OpenAPI 校验工具可后续选择 Redocly、Spectral 或等价 CLI；关键是把契约校验和 contract tests 同时作为 required checks。

## 5. Main / Release

`main` 和 release tag 阶段负责把通过 PR 门禁的代码变成可部署镜像，并把版本写入 GitOps 目标状态。

| 阶段 | 要求 |
| --- | --- |
| 镜像构建 | 分别构建 API 和 Admin image，tag 使用 commit SHA、语义化版本或 `dev-YYYYMMDD-HHMM`。 |
| 双 Registry 推送 | 同一 tag 推送到 GHCR 和阿里云 Registry；中国环境下 K8s 优先拉取阿里云 Registry，GHCR 保留为备份和发布记录。 |
| GitOps tag 更新 | 更新 GitOps repo 或本仓库约定的 values/tag 文件，由 Flux 负责同步。 |
| 部署后验证 | 等待 K8s rollout 完成，执行 `/health` 和 quick live eval。 |
| 发布记录 | 记录镜像 tag、Git SHA、OpenAPI 版本、eval 报告和部署环境。 |

SBOM、镜像扫描、依赖漏洞扫描、Helm/K8s 安全扫描可以后续补齐，但不应阻塞第一阶段把 build / push / GitOps / rollout 闭环跑通。

## 6. GitOps 部署约束

本仓库不直接 `kubectl apply`、`kubectl set image` 或手动改集群对象来完成常规发布。

部署应遵守以下约束：

- 应用仓库构建并发布镜像。
- GitOps tag / values 变更作为唯一目标状态变更入口。
- Flux 负责把目标状态同步到 K8s。
- K8s 运行时 Secret 由 Kubernetes Secret、GitHub Secrets 或批准的外部 Secret Manager 管理。
- API、Admin 和后台服务必须保持 k8s 无状态；业务数据、session、checkpoint、审计和报告落 PostgreSQL / Object Storage 等外部持久化组件。
- 生产或 dev 环境排障可以读取 rollout、pod、event 和日志，但不能把手工 kubectl 修改作为发布路径。

如果后续采用独立 GitOps 仓库，应用仓库 workflow 只提交 image tag / values PR 或直接推送受控分支；如果 GitOps 文件保留在本仓库，也应通过 Git commit 触发 Flux，而不是在 workflow 中绕过 GitOps 直接修改集群。

## 7. Release Gate

发布门禁分两层落地：

| 阶段 | 内容 |
| --- | --- |
| 第一阶段 | quick live eval：部署后调用 dev API `/health`，再用 `evals.cli` 对 live target 跑 quick suite。 |
| 后续阶段 | 盲测核心集、红线 suite、固定回归集、基线对比和失败分类报告。 |

quick live eval 需要从 Secret 注入 `TARGET_BASE_URL` 和 `AGENT_API_TOKEN`，不能把 token 写入仓库或文档。红线 suite 一票否决，至少覆盖跨租户泄露、无依据报价、越权动作、绕过人工确认、高风险自动回复和 trace 缺失。

建议发布前最终检查顺序：

```text
PR required checks passed
-> images pushed to GHCR and Aliyun Registry
-> GitOps target updated
-> Flux sync healthy
-> K8s rollout complete
-> /health passed
-> quick live eval passed
-> release gate report archived
```

## 8. 失败通知

当前失败通知沿用 CodeQL 邮件通知：

- job：`Notify security gate blocked`
- 触发：`CodeQL SAST` 失败
- 收件人：`SECURITY_NOTIFY_TO`
- SMTP 配置：`SMTP_*`、`MAIL_FROM`

后续可扩展部署失败通知，但要保持通知分层：

| 失败类型 | 建议通知 |
| --- | --- |
| SAST / 安全门禁失败 | 沿用 CodeQL 邮件通知。 |
| PR tests 失败 | GitHub required checks 即时反馈，默认不额外发邮件。 |
| 镜像构建或推送失败 | GitHub Actions 失败即可；需要时增加邮件或 Teams / Slack。 |
| GitOps 更新失败 | 通知 release owner，并附 workflow run、目标 tag 和 GitOps diff。 |
| K8s rollout / health / live eval 失败 | 通知 release owner，并附 rollout 状态、health 响应、eval 报告路径和回滚建议。 |

部署失败通知不得包含 kubeconfig、token、数据库 URL、LLM key、Registry password 或任何 Secret 明文。

## 9. 当前缺口

当前需要补齐的工程化缺口：

- `pr-checks` workflow：Markdown / OpenAPI、Python tests、eval CLI unit tests、Helm lint / template。
- API / Admin Dockerfile 或构建配置的稳定入口。
- GHCR 和阿里云 Registry 双推送 workflow。
- image tag 命名、发布记录和回滚策略。
- GitOps tag / values 更新方式。
- Flux sync、K8s rollout、`/health` 和 quick live eval 的自动化验证。
- release gate 报告归档位置和失败分类格式。
- SBOM、镜像扫描、依赖漏洞扫描和 Helm/K8s 安全扫描。
- 部署失败通知和回滚通知。
- Branch Protection required checks 配置。

这些缺口应按可验证闭环推进，不要一次性把所有安全扫描和质量平台都塞进第一版。

## 10. 分阶段落地顺序

### 10.1 第一阶段：PR 可拦截

- 保留并启用 CodeQL SAST required check。
- 新增 Markdown / OpenAPI 校验。
- 新增 Python unit / contract / integration tests。
- 新增 eval CLI unit tests。
- 新增 Helm lint / template。
- 配置 Branch Protection，把稳定 checks 设为 required。

### 10.2 第二阶段：镜像可发布

- 固定 API / Admin 构建入口。
- 构建并 tag API / Admin images。
- 推送 GHCR。
- 推送阿里云 Registry。
- 输出镜像 digest 和发布摘要。

### 10.3 第三阶段：GitOps 可部署

- 固定 GitOps image tag / values 文件。
- workflow 更新 tag / values。
- Flux 同步 dev 环境。
- 等待 K8s rollout 完成。
- 执行 API/Admin `/health`。

### 10.4 第四阶段：上线可判定

- 接入 quick live eval。
- 固化 release gate 报告。
- 增加盲测核心集和红线 suite。
- 失败用例沉淀为回归集。
- 根据稳定性再补 SBOM、镜像扫描、依赖漏洞扫描和 Helm/K8s 安全扫描。

### 10.5 第五阶段：通知和治理

- 扩展部署失败通知。
- 固定回滚通知模板。
- 定期检查 GitHub Secrets、Registry 权限和 GitOps token 权限。
- 汇总 release 质量趋势、eval 分数、红线失败和部署失败原因。
