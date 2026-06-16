# Deployment

本文记录 `ecommerce-cs-agent` 当前 dev 环境底座、应用部署前置条件和评测连接方式。业务 Agent API、Admin Web 和评测 worker 尚未部署时，以本文作为 Deploy 项目和应用项目之间的环境契约。

## 当前环境

| 项目 | 值 |
| --- | --- |
| 环境名称 | `ecommerce-cs-agent-dev` |
| Kubernetes | `k3s v1.35.4+k3s1` |
| kubeconfig | `~/.kube/bpg-debian12-master-public.yaml` |
| context | `default` |
| namespace | `ecommerce-cs-agent-dev` |
| 部署方式 | FluxCD GitOps |
| GitOps 状态 | `fhg-gitops-repo` 已应用 `main@sha1:6574dd21fbb69f057129cdb27cd27734fb9a5089` |
| Ingress controller | Traefik |
| TLS | cert-manager `letsencrypt-http01` ClusterIssuer Ready |

节点状态由 Deploy 项目确认：`master`、`agent-0` 均为 Ready。Codex 本机可通过公网 kubeconfig 访问集群。

## 域名

| 用途 | 域名 | 当前状态 |
| --- | --- | --- |
| Agent API | `api.ecommerce-cs-agent-dev.fcihome.com` | FRP HTTP/HTTPS customDomain 已预留；业务 Service 未部署，Ingress 暂未创建 |
| Admin Web | `admin.ecommerce-cs-agent-dev.fcihome.com` | FRP HTTP/HTTPS customDomain 已预留；业务 Service 未部署，Ingress 暂未创建 |

业务应用部署后再创建 API/Admin Ingress，并绑定到对应 Service。

## PostgreSQL

| 项目 | 值 |
| --- | --- |
| Service | `postgres.ecommerce-cs-agent-dev.svc.cluster.local:5432` |
| PostgreSQL | `16.14` |
| Database | `cs_agent` |
| User | `cs_agent` |
| SSL | 集群内使用 `sslmode=disable` |
| Storage | StatefulSet Ready，PVC `20Gi` |
| Extensions | `pgcrypto`、`vector` 已启用 |
| Auth Secret | `ecommerce-postgres-auth` |

生产业务数据、LangGraph checkpoint、规则、知识、反馈、审计和 Admin session 数据应落 PostgreSQL，不依赖 Pod 本地状态。

## Object Storage

| 项目 | 值 |
| --- | --- |
| Provider | MinIO |
| Endpoint | `http://minio.ecommerce-cs-agent-dev.svc.cluster.local:9000` |
| Bucket | `ecommerce-cs-agent-dev` |
| Region | `us-east-1` |
| Path style | `true` |
| Auth Secret | `ecommerce-minio-auth` |

Deploy 项目已创建 bucket 和应用 access user，并完成手动备份上传验证。商品原始文件、JSONL 归档、训练导出和评测报告等对象数据应写入该 bucket。

## Container Registry

| 项目 | 值 |
| --- | --- |
| Registry | `ghcr.io/liuyenhui` |
| imagePullSecret | `ghcr-auth` |
| Namespace | `ecommerce-cs-agent-dev` |

推送权限走 GitHub/GHCR 凭据，不要把 token 写入 Git。业务 chart 或 Kustomize 清单应引用 `ghcr-auth`。

## CI/CD 安全门禁

当前先落地 GitHub CodeQL / GitHub Advanced Security 作为 PR 阶段的 SAST 必过检查，拦截 AI 生成代码中的低级安全错误。建议流水线顺序：

```text
PR -> CodeQL SAST -> failure email notification -> tests/build -> image publish -> GitOps deploy
```

CodeQL workflow：

- 文件：`.github/workflows/codeql.yml`
- 当前扫描：GitHub Actions / JavaScript 脚本；远端仓库提交 Python 源码后再扩展 `python`
- 触发：`pull_request` 到 `main`、`push` 到 `main`、每周定时扫描
- 仓库公开后，workflow 上传 SARIF 到 GitHub Code Scanning，同时本地解析 SARIF；发现 CodeQL alert 时让 `CodeQL SAST` job 失败
- 分支保护：GitHub 账号/仓库计划支持后，在 Branch Protection 中把 `CodeQL SAST` 设为 required check
- 查询规则：`security-extended`、`security-and-quality`

安全门禁失败时发送拦截通知：

- 收件人：`46164072@qq.com`
- 邮件 job：`Notify security gate blocked`
- SMTP 配置来自 GitHub Secrets，不写入仓库：
  - `SMTP_HOST`
  - `SMTP_PORT`
  - `SMTP_USERNAME`
  - `SMTP_PASSWORD`
  - `MAIL_FROM`
  - `SECURITY_NOTIFY_TO=46164072@qq.com`

后续优化 CI/CD 时再补充：

- SonarQube：代码质量、安全规则、重复度和复杂度治理。
- Snyk 或 Dependabot：依赖漏洞扫描。
- 镜像扫描：发布镜像前扫描 OS/package CVE。
- Helm/K8s 扫描：检查 `privileged`、RBAC 过宽、Secret 明文、Ingress/TLS、NetworkPolicy。

## Secrets

运行时 Secret：`ecommerce-cs-agent-runtime`

| Key | 状态 |
| --- | --- |
| `DATABASE_URL` | 已预留 |
| `OBJECT_STORAGE_ENDPOINT` | 已预留 |
| `OBJECT_STORAGE_BUCKET` | 已预留 |
| `OBJECT_STORAGE_REGION` | 已预留 |
| `OBJECT_STORAGE_ACCESS_KEY_ID` | 已预留 |
| `OBJECT_STORAGE_SECRET_ACCESS_KEY` | 已预留 |
| `LLM_API_KEY` | 需要填入真实值 |
| `LLM_BASE_URL` | 需要填入真实值 |
| `LLM_MODEL` | 需要填入真实值 |
| `SESSION_SECRET` | 已预留 |
| `JWT_SECRET` | 已预留 |
| `AGENT_API_TOKEN` | 已预留 |
| `ADMIN_INITIAL_EMAIL` | 已预留 |
| `ADMIN_INITIAL_PASSWORD_HASH` | 已预留 |

其他 Secret：

| Secret | 用途 |
| --- | --- |
| `ecommerce-postgres-auth` | PostgreSQL `database`、`username`、`password` |
| `ecommerce-minio-auth` | MinIO `root-user`、`root-password`、`bucket`、`access-key`、`secret-key` |
| `ghcr-auth` | GHCR `.dockerconfigjson` |

不要在 Git、普通文档或聊天记录中保存密钥明文。

## Network

Flux controller 当前使用：

```bash
HTTP_PROXY=http://192.168.1.198:1087
HTTPS_PROXY=http://192.168.1.198:1087
```

业务 Pod 尚未配置代理。如果 Agent API 调用 LLM 需要代理，应在 API chart/env 中配置同类 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY`。`NO_PROXY` 至少应覆盖 Kubernetes Service 域名、Pod/Service 网段、`localhost`、`127.0.0.1`、PostgreSQL 和 MinIO 集群内地址。

Redis 暂不部署。第一版不得把 Redis 作为必需依赖；后续需要 session cache、队列或异步任务时再引入。

## Runtime Configuration

应用镜像部署后，Pod 应从 `ecommerce-cs-agent-runtime` 注入运行时环境变量。建议的最小环境如下：

```bash
DATABASE_URL=postgresql://cs_agent:<from-secret>@postgres.ecommerce-cs-agent-dev.svc.cluster.local:5432/cs_agent?sslmode=disable
OBJECT_STORAGE_ENDPOINT=http://minio.ecommerce-cs-agent-dev.svc.cluster.local:9000
OBJECT_STORAGE_BUCKET=ecommerce-cs-agent-dev
OBJECT_STORAGE_REGION=us-east-1
OBJECT_STORAGE_PATH_STYLE=true
LLM_BASE_URL=<from-secret>
LLM_MODEL=<from-secret>
AGENT_API_TOKEN=<from-secret>
```

## Evaluation

当前还没有业务 Agent API，因此 `TARGET_BASE_URL` 暂不可用。

业务 Agent API 部署完成后：

```bash
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com
```

Live 评测建议使用：

```bash
AGENT_API_TOKEN=<from-secret> python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

鉴权建议：

```text
Authorization: Bearer <AGENT_API_TOKEN>
```

`AGENT_API_TOKEN` 从 `ecommerce-cs-agent-runtime` Secret 获取，不写入代码仓库。

## 仍缺内容

- 真实 `LLM_API_KEY`
- 真实 `LLM_BASE_URL`
- 真实 `LLM_MODEL`
- Agent API 镜像与 Deployment/Service/Ingress
- Admin Web 镜像与 Deployment/Service/Ingress
- 评测 worker 镜像或 CronJob/Job 清单
- 应用数据库 schema migration 方案
- API/Admin 健康检查路径和 readiness/liveness probe

## 应用部署完成后的验收

```bash
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl get nodes
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get pods,svc,ingress,secrets
curl -fsS https://api.ecommerce-cs-agent-dev.fcihome.com/health
curl -fsS https://admin.ecommerce-cs-agent-dev.fcihome.com/
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com AGENT_API_TOKEN=<from-secret> python -m evals.cli run-suite --suite quick --target live
```

## 应用镜像与 Helm

默认镜像名：

```bash
API_IMAGE=ghcr.io/liuyenhui/ecommerce-cs-agent-api:<tag>
ADMIN_IMAGE=ghcr.io/liuyenhui/ecommerce-cs-agent-admin:<tag>
```

构建示例：

```bash
docker build -f Dockerfile.api -t ghcr.io/liuyenhui/ecommerce-cs-agent-api:<tag> .
docker build -f admin-web/Dockerfile -t ghcr.io/liuyenhui/ecommerce-cs-agent-admin:<tag> .
```

Helm 渲染检查：

```bash
helm lint deploy/helm/ecommerce-cs-agent -f deploy/helm/ecommerce-cs-agent/values-dev.yaml
helm template ecommerce-cs-agent deploy/helm/ecommerce-cs-agent \
  -n ecommerce-cs-agent-dev \
  -f deploy/helm/ecommerce-cs-agent/values-dev.yaml
```

部署时覆盖镜像 tag：

```bash
helm upgrade --install ecommerce-cs-agent deploy/helm/ecommerce-cs-agent \
  -n ecommerce-cs-agent-dev \
  -f deploy/helm/ecommerce-cs-agent/values-dev.yaml \
  --set api.image.tag=<tag> \
  --set admin.image.tag=<tag>
```
