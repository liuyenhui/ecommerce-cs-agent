# 部署工件边界

本文说明 `ecommerce-cs-agent` 应用仓库、GitOps / Flux / Helm 仓库和运行时集群之间的职责边界。它用于避免把应用实现、镜像发布、Helm values、Secret 和集群排障混在一个提交里。

相关文档：

- [Deployment](deployment.md)：当前 dev 环境、域名、Secret、Registry、live eval 和部署验收。
- [CI/CD](ci-cd.md)：应用仓库侧的测试、镜像构建、镜像推送和 GitOps 更新流程。
- [Development Readiness](development-readiness.md)：第一版开发范围、验收命令和 API 覆盖状态。

## 1. 仓库职责

| 仓库 / 系统 | 职责 | 不负责 |
| --- | --- | --- |
| 应用仓库 `ecommerce-cs-agent` | 应用源码、OpenAPI 契约、评测工具、测试、镜像构建定义、Helm chart、应用版本号、开发和部署文档。 | 直接保存真实 Secret、直接修改集群线上对象、长期维护集群入口和证书。 |
| GitOps / Flux 仓库 | dev values、namespace、基础设施、Secret 引用、imagePullSecrets、cert-manager、Flux Kustomization / HelmRelease。 | 业务逻辑、OpenAPI 契约、评测规则、应用代码测试、镜像构建。 |
| Kubernetes 集群 | 运行 API / Admin Pod、PostgreSQL、MinIO、Ingress、TLS、运行时 Secret 和镜像拉取。 | 作为源码或文档事实来源。 |
| GitHub Actions | PR 检查、CodeQL、测试、镜像构建、GHCR / 阿里云 Registry 推送、触发 GitOps tag 更新。 | 保存明文密钥、绕过 GitOps 直接改生产配置。 |

当前 Helm chart 位于应用仓库 `deploy/helm/ecommerce-cs-agent`。GitOps 仓库的 dev `HelmRelease` 通过 `GitRepository` 指向应用仓库 chart，并用 GitOps repo 中的 values 固定 dev 镜像 tag、Ingress、Secret 引用和代理配置。

## 2. 镜像和版本流转

建议的镜像发布链路：

```text
应用提交 SHA 或 dev timestamp
-> GitHub Actions 构建 API / Admin 镜像
-> 推送 GHCR 和阿里云 Registry
-> 更新 GitOps values / image tag
-> Flux reconcile HelmRelease
-> K8s 拉取阿里云 Registry 镜像
-> /health 和 live eval 验收
```

镜像 tag 规则：

| 场景 | 建议 tag | 说明 |
| --- | --- | --- |
| PR 临时验证 | `pr-<number>-<short_sha>` | 可用于临时环境，不作为稳定部署引用。 |
| dev 主线 | `dev-YYYYMMDD-HHMM-<short_sha>` | 便于按时间和 commit 定位。 |
| release candidate | `rc-<version>-<short_sha>` | 发布候选，必须经过 release gate。 |
| 正式版本 | `vX.Y.Z` | 只指向已验收 commit。 |

中国网络环境下，dev 集群优先拉取阿里云 Registry；GHCR 保留为备份镜像和 GitHub 原生发布记录。

## 3. Secret 流转

Secret 只以引用形式跨文档和配置流转。

| 层级 | 保存内容 | 说明 |
| --- | --- | --- |
| GitHub Secrets | Registry 推送凭据、SMTP 通知凭据、后续 GitOps 写入凭据。 | 只通过 Actions 注入，不写入仓库。 |
| Kubernetes Secrets | `DATABASE_URL`、对象存储凭据、LLM 配置、`AGENT_API_TOKEN`、session/JWT secret。 | 应用 Pod 通过环境变量或挂载读取。 |
| 应用数据库 | Secret 引用、审计记录、配置状态。 | 不保存明文平台 token 或私钥。 |
| 文档 | Secret key 名、Secret 对象名、占位符 `<from-secret>`。 | 不保存真实值。 |

运行时 Secret 以 [Deployment](deployment.md) 的 `ecommerce-cs-agent-runtime` 为准。提交前不要把 `.env`、kubeconfig、registry token 或 LLM key 加入 Git。

## 4. Helm / GitOps 边界

应用仓库应输出：

- API / Admin 镜像 tag。
- OpenAPI 和评测结果。
- 需要新增或变更的环境变量 key。
- 数据库迁移版本。
- 健康检查和 live eval 结果；dev 环境由 `scripts/run_dev_release_gate.py` 生成 `reports/release-gate/dev-release-gate.md`，GitHub Actions 上传为 `dev-release-gate-<image_tag>` artifact。

GitOps / Flux 仓库应维护：

- HelmRelease、基础设施、Ingress/TLS 环境约定、Secret 引用和 `imagePullSecrets`。
- API / Admin 镜像 repository、tag 和 pull policy。
- 资源请求、探针、环境变量注入、代理和 `NO_PROXY`。
- PostgreSQL、MinIO、pgvector、TLS、域名和 Flux 状态。

如果业务改动需要新增环境变量，应用 PR 必须同时更新文档，GitOps PR 再更新 values 和 Secret 引用。不得在应用代码里写死 dev 域名、数据库地址或 Secret 值。

## 5. 部署验收

部署完成后至少执行：

```bash
curl -fsS https://api.ecommerce-cs-agent-dev.fcihome.com/health
curl -fsS https://admin.ecommerce-cs-agent-dev.fcihome.com/health
curl -fsS https://system-admin.ecommerce-cs-agent-dev.fcihome.com/health
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com \
  AGENT_API_TOKEN=<from-secret> \
  python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

拆分系统后台站点后，GitOps values 必须同时表达 customer Admin host 和 system Admin host。两个 host 可以复用同一 Admin 镜像，但 Ingress host、登录页、Cookie / session 名、路由守卫和 API 鉴权域必须独立。

`AGENT_API_TOKEN` 从 Kubernetes Secret 或安全的临时环境变量读取，不写入命令历史共享记录、文档或聊天。

验收摘要应记录：

- 应用 commit / image tag。
- Helm release revision 或 GitOps commit。
- API/Admin `/health` 状态。
- live eval pass/fail 和 `decision_id` 摘要。
- 若失败，引用 [Runbook](runbook.md) 中的排查分支。

应用仓库提供统一验收入口：

```bash
python scripts/run_dev_release_gate.py \
  --commit-sha <commit-sha> \
  --image-tag <image-tag> \
  --gitops-commit <gitops-commit>
```

该脚本只通过 GitOps / Flux 资源等待目标状态，不使用 `kubectl set image` 或手工 Helm upgrade。`AGENT_API_TOKEN` 优先从环境变量读取；若未提供，则从 Kubernetes Secret `ecommerce-cs-agent-runtime` 读取后只传给 eval 子进程，报告会脱敏。拆站完成后，发布报告必须分别记录 API、Customer Admin 和 System Admin health。

## 6. 排查归属

| 问题 | 首选排查位置 |
| --- | --- |
| OpenAPI 契约、评测用例、业务响应字段错误 | 应用仓库 |
| API 运行时 500、鉴权、幂等、trace、数据库读写 | 应用仓库 |
| 镜像 tag 不存在、imagePullBackOff、registry 登录失败 | CI/CD + GitOps / Deploy 仓库 |
| Ingress、TLS、DNS、Flux reconcile、Helm values | GitOps / Deploy 仓库 |
| PostgreSQL、MinIO、K8s Secret、PVC、集群网络 | GitOps / Deploy 仓库或集群运维 |
| live eval 401/403/422/500 | 先看应用响应，再按 [Runbook](runbook.md) 分支定位 |

跨仓库协作时，应用仓库提交应说明需要 GitOps 侧同步的 image tag、env key、Secret key 和验收命令。
