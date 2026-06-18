# Deployment

本文记录 `ecommerce-cs-agent` 当前 dev 环境底座、应用部署状态、镜像发布链路和评测连接方式。本文作为 Deploy 项目和应用项目之间的环境契约，敏感值只记录 Secret key，不记录明文。

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

## 当前部署快照

更新时间：`2026-06-17`

| 项目 | 值 |
| --- | --- |
| Helm release | `ecommerce-cs-agent` |
| Namespace | `ecommerce-cs-agent-dev` |
| Helm status | `deployed` |
| Helm revision | `6` |
| API image | `registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-api:dev-20260616-1459` |
| Admin image | `registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-admin:dev-20260616-1459` |
| API Deployment | `1/1 Running` |
| Admin Deployment | `1/1 Running` |
| imagePullSecrets | `aliyun-registry-auth`、`ghcr-auth` |
| Migration | `001_initial.sql` 已写入 `schema_migration`，时间 `2026-06-16 15:23:42 +0800` |

当前公网验证：

| 检查项 | 结果 |
| --- | --- |
| `https://api.ecommerce-cs-agent-dev.fcihome.com/health` | `200`，返回 `{"status":"ok","service":"ecommerce-cs-agent-api","environment":"development"}` |
| `https://admin.ecommerce-cs-agent-dev.fcihome.com/health` | `200`，返回 `ok` |
| `https://system-admin.ecommerce-cs-agent-dev.fcihome.com/health` | `2026-06-18` DNS 已解析到 `47.113.204.168`；当前 HTTPS 到达 Traefik default cert，`/health` 返回 `404`，待发布新 Ingress/TLS 后复验 |
| `cs-agent-dev-tls` | `READY=True` |
| live quick eval | 本地 `evals.cli` 已恢复；未传 `AGENT_API_TOKEN` 时只能安全验证 `/health`，完整 quick eval 需从 Secret 读取 token 后执行 |

## 域名

| 用途 | 域名 | 当前状态 |
| --- | --- | --- |
| Agent API | `api.ecommerce-cs-agent-dev.fcihome.com` | DNS -> `47.113.204.168`，HTTPS 可访问，Ingress 已创建 |
| Customer Admin Web | `admin.ecommerce-cs-agent-dev.fcihome.com` | DNS -> `47.113.204.168`，HTTPS 可访问，Ingress 已创建；只承载公开宣传页、客户登录页和客户后台 |
| System Admin Web | `system-admin.ecommerce-cs-agent-dev.fcihome.com` | DNS -> `47.113.204.168`；应用 chart / Admin Web 已按此 host 实现拆站，当前线上仍需发布 Ingress/TLS 后完成 HTTPS 和 `/health` 验证 |
| System Admin Web alias | `ops-admin.ecommerce-cs-agent-dev.fcihome.com` | 可选别名；只有在 DNS / 证书策略需要时启用 |

FRP 日志已确认 `cs-agent-dev-http` API/Admin/root 三个 Host 注册成功。TLS 证书 SAN 已包含 API/Admin/root dev 域名，HTTPS 校验通过。`system-admin.ecommerce-cs-agent-dev.fcihome.com` 的 DNS 已生效，但当前线上证书仍是 Traefik default cert；发布新 Helm/GitOps 目标状态后，需要确认 Ingress host、`cs-agent-dev-tls` SAN、system Admin `/health` 和登录页均已独立可访问。

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
| 主拉取 Registry | `registry.cn-beijing.aliyuncs.com/threepeople` |
| 备份 Registry | `ghcr.io/liuyenhui` |
| 主 imagePullSecret | `aliyun-registry-auth` |
| 备份 imagePullSecret | `ghcr-auth` |
| Namespace | `ecommerce-cs-agent-dev` |

中国环境下 K8s 优先从阿里云 Registry 拉取镜像，GHCR 保留作为备份和 GitHub 原生发布记录。

默认镜像：

```bash
API_IMAGE=registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-api:<tag>
ADMIN_IMAGE=registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-admin:<tag>
```

备份镜像：

```bash
API_IMAGE_BACKUP=ghcr.io/liuyenhui/ecommerce-cs-agent-api:<tag>
ADMIN_IMAGE_BACKUP=ghcr.io/liuyenhui/ecommerce-cs-agent-admin:<tag>
```

凭据处理：

- GitHub Actions 使用 `ALIYUN_REGISTRY_USERNAME`、`ALIYUN_REGISTRY_PASSWORD` 推送阿里云 Registry。
- K8s namespace 内使用 `aliyun-registry-auth` 拉取阿里云镜像。
- GHCR 使用 GitHub/GHCR 凭据和 `ghcr-auth` 作为备份。
- 不要把 registry token 写入 Git、普通文档或聊天记录。

## CI/CD 安全门禁

当前先落地 GitHub CodeQL / GitHub Advanced Security 作为 PR 阶段的 SAST 必过检查，拦截 AI 生成代码中的低级安全错误。镜像发布从本机临时构建/节点 `containerd` 导入，调整为远端 CI 构建并发布。

建议流水线顺序：

```text
PR / main
-> CodeQL SAST
-> Python tests
-> Helm lint/template
-> GitHub Actions build API/Admin
-> push GHCR + Aliyun Registry
-> Helm/GitOps 更新 image tag
-> K8s 从阿里云 Registry 拉取部署
-> /health 验证
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

Watchtower 不用于当前 dev 环境。Watchtower 适合 docker compose 服务器自动更新；当前环境是 Kubernetes/Helm，应使用 GitHub Actions build/push、Helm/GitOps 更新 image tag、K8s 拉取部署的链路。

## Secrets

运行时 Secret：`ecommerce-cs-agent-runtime`

| Key | 状态 |
| --- | --- |
| `DATABASE_URL` | 已写入 |
| `OBJECT_STORAGE_ENDPOINT` | 已写入 |
| `OBJECT_STORAGE_BUCKET` | 已写入 |
| `OBJECT_STORAGE_REGION` | 已写入 |
| `OBJECT_STORAGE_ACCESS_KEY_ID` | 已写入 |
| `OBJECT_STORAGE_SECRET_ACCESS_KEY` | 已写入 |
| `LLM_API_KEY` | 已写入 |
| `LLM_BASE_URL` | 已写入 |
| `LLM_MODEL` | 已写入 |
| `SESSION_SECRET` | 已写入 |
| `JWT_SECRET` | 已写入 |
| `AGENT_API_TOKEN` | 已写入 |
| `ADMIN_INITIAL_EMAIL` | 已写入 |
| `ADMIN_INITIAL_PASSWORD_HASH` | 已写入 |

其他 Secret：

| Secret | 用途 |
| --- | --- |
| `ecommerce-postgres-auth` | PostgreSQL `database`、`username`、`password` |
| `ecommerce-minio-auth` | MinIO `root-user`、`root-password`、`bucket`、`access-key`、`secret-key` |
| `aliyun-registry-auth` | 阿里云 Registry `.dockerconfigjson` |
| `ghcr-auth` | GHCR `.dockerconfigjson` |

不要在 Git、普通文档或聊天记录中保存密钥明文。

## Network

Flux controller 当前使用：

```bash
HTTP_PROXY=http://192.168.1.198:1087
HTTPS_PROXY=http://192.168.1.198:1087
```

API Pod 已配置代理：

```bash
HTTP_PROXY=http://192.168.1.198:1087
HTTPS_PROXY=http://192.168.1.198:1087
NO_PROXY=localhost,127.0.0.1,.svc,.cluster.local,postgres.ecommerce-cs-agent-dev.svc.cluster.local,minio.ecommerce-cs-agent-dev.svc.cluster.local
```

后续如果 LLM 直连稳定，可以在 chart values 中关闭业务 Pod 代理。

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

当前 dev API 已部署，公网 `TARGET_BASE_URL`：

```bash
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com
```

Live 评测建议使用：

```bash
AGENT_API_TOKEN=<from-secret> python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

`evals.cli` 的 quick suite 会先检查 `GET /health`，再按契约发送最小 `POST /v1/reply-decisions` 请求，并输出 pass/fail、HTTP 状态、`decision_id`、`action` 和 `decision_status` 摘要。命令从环境变量读取 `AGENT_API_TOKEN` 并发送 `Authorization: Bearer <token>`，输出不会打印 token、secret 或完整 Authorization header。拆站发布验收必须分别记录 API、Customer Admin 和 System Admin health，不能用单个 Admin health 代替。

鉴权建议：

```text
Authorization: Bearer <AGENT_API_TOKEN>
```

`AGENT_API_TOKEN` 从 `ecommerce-cs-agent-runtime` Secret 获取，不写入代码仓库。

## 仍缺内容

部署环境当前已闭环；剩余是工程化和业务实现项：

- 完整 GitHub Actions 构建并推送 API/Admin 镜像到 GHCR 和阿里云 Registry。
- Helm/GitOps image tag 自动更新流程。
- 真实 LLM 调用和 LangGraph/决策编排。
- PostgreSQL 决策记录、checkpoint、audit 的业务读写。
- Admin 登录、初始化管理员、后台页面和权限模型。
- 评测 worker 镜像或 CronJob/Job 清单。

## 应用部署完成后的验收

```bash
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl get nodes
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get pods,svc,ingress,secrets
curl -fsS https://api.ecommerce-cs-agent-dev.fcihome.com/health
curl -fsS https://admin.ecommerce-cs-agent-dev.fcihome.com/health
curl -fsS https://system-admin.ecommerce-cs-agent-dev.fcihome.com/health
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com AGENT_API_TOKEN=<from-secret> python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

系统后台拆站完成前，第三条 health 命令是发布目标检查项；不能把 DNS 解析成功、Traefik default cert、或 `admin.ecommerce-cs-agent-dev.fcihome.com` 上的系统后台 tab 当作验收通过。

## 应用镜像与 Helm

dev 环境默认使用阿里云镜像：

```bash
API_IMAGE=registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-api:<tag>
ADMIN_IMAGE=registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-admin:<tag>
```

GHCR 备份镜像：

```bash
API_IMAGE_BACKUP=ghcr.io/liuyenhui/ecommerce-cs-agent-api:<tag>
ADMIN_IMAGE_BACKUP=ghcr.io/liuyenhui/ecommerce-cs-agent-admin:<tag>
```

正式构建和推送应由 GitHub Actions 远端完成，同时推送阿里云 Registry 和 GHCR。本机构建、节点 `containerd` 导入只作为临时兜底，不作为常规部署链路。

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

拆分系统后台站点时，Helm values 还必须显式表达 customer Admin host 和 system Admin host。两个 host 可以暂时复用同一 Admin 镜像，但 Ingress、前端路由守卫、Cookie / session 名和 API 鉴权域必须拆开。
