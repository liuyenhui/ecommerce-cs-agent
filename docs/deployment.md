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
| GitOps 状态 | `fhg-gitops-repo` 已由 Deploy Dev GitOps 更新到 `main@sha1:e6f4b294910ff6b114f183e96775aedde9b140c1` |
| Ingress controller | Traefik |
| TLS | cert-manager `letsencrypt-http01` ClusterIssuer Ready |

节点状态由 Deploy 项目确认：`master`、`agent-0` 均为 Ready。Codex 本机执行 kubectl 前必须先确认 context 指向 dev K3s；当前公开验证可用 DNS / HTTPS / release gate 证据确认。

## 当前部署快照

更新时间：`2026-06-18`

| 项目 | 值 |
| --- | --- |
| Helm release | `ecommerce-cs-agent` |
| Namespace | `ecommerce-cs-agent-dev` |
| Helm status | `deployed` |
| Helm revision | Deploy Dev GitOps 已应用 `0.1.0+fe6162288c6d` |
| API image | `registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-api:sha-fe6162288c6d` |
| Admin image | `registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-admin:sha-fe6162288c6d` |
| API Deployment | `1/1 Running` |
| Admin Deployment | `1/1 Running` |
| imagePullSecrets | `aliyun-registry-auth`、`ghcr-auth` |
| Migration | `001_initial.sql` 已写入 `schema_migration`，时间 `2026-06-16 15:23:42 +0800` |

当前公网验证：

| 检查项 | 结果 |
| --- | --- |
| `https://api.ecommerce-cs-agent-dev.fcihome.com/health` | `200`，返回 `{"status":"ok","service":"ecommerce-cs-agent-api","environment":"production"}` |
| `https://admin.ecommerce-cs-agent-dev.fcihome.com/health` | `200`，返回 `ok` |
| `https://system-admin.ecommerce-cs-agent-dev.fcihome.com/health` | `200`，返回 `ok`；DNS 解析到 `47.113.204.168` |
| 公开 TLS | `system-admin.ecommerce-cs-agent-dev.fcihome.com` 证书由 Let's Encrypt 签发，SAN 覆盖 `api.ecommerce-cs-agent-dev.fcihome.com`、`admin.ecommerce-cs-agent-dev.fcihome.com`、`system-admin.ecommerce-cs-agent-dev.fcihome.com` |
| live quick eval | Deploy Dev release gate 已在 GitHub runner 中通过 quick live eval；本机未传 `AGENT_API_TOKEN` 时只能安全验证 `/health` |

## 域名

| 用途 | 域名 | 当前状态 |
| --- | --- | --- |
| Agent API | `api.ecommerce-cs-agent-dev.fcihome.com` | DNS -> `47.113.204.168`，HTTPS 可访问，Ingress 已创建 |
| Customer Admin Web | `admin.ecommerce-cs-agent-dev.fcihome.com` | DNS -> `47.113.204.168`，HTTPS 可访问，Ingress 已创建；只承载公开宣传页、客户登录页和客户后台 |
| System Admin Web | `system-admin.ecommerce-cs-agent-dev.fcihome.com` | DNS -> `47.113.204.168`，HTTPS 可访问，`/health` 返回 `200 ok`；只承载系统后台登录页和系统后台 |
| System Admin Web alias | `ops-admin.ecommerce-cs-agent-dev.fcihome.com` | 可选别名；只有在 DNS / 证书策略需要时启用 |

FRP 继续复用 K3s 侧 `frp-system/bpg-frpc` 的 `cs-agent-dev-http` proxy，不新增 frpc，也不配置 `type=https`。外层 ai-agent Traefik / frps 已追加 API / Customer Admin / System Admin Host 并重启生效；公开 TLS 证书 SAN 已包含 API/Admin/root/System Admin dev 域名，HTTPS 校验通过。浏览器运行时验证显示 Customer Admin host 只请求 `/v1/admin/auth/me` 且不展示系统后台入口，System Admin host 只请求 `/v1/system-admin/auth/me` 且不复用客户登录页。cert-manager HTTP-01 如果出现公网 `404`，不要只查 K8s Ingress/TLS，还要同步检查外层 ai-agent Traefik `frps_vhost` Host rule 和 K3s `bpg-frpc` customDomains。

## FRP / FRPC 公网入口

`ecommerce-cs-agent-dev` 的公网入口由 ai-agent 外层 Traefik/FRPS 和 K3s 内部 frpc 共同组成：

| 层级 | 配置 |
| --- | --- |
| 外层入口 | `ai-agent`，公网 IP `47.113.204.168` |
| 外层 Traefik | Docker 容器 `erp_ai_agent_traefik`，负责公网 HTTPS 终止 |
| 外层 FRPS | Docker 容器 `erp_ai_agent_frps`，HTTP vhost 端口 `8081` |
| 外层配置来源 | ai-agent：`/root/open_erp_agent/deploy/ai-agent/docker-compose.yaml` |
| 本地参考路径 | `/Users/huiliu/Documents/software/open_erp_agent/deploy/ai-agent/docker-compose.yaml` |
| K3s frpc | namespace `frp-system`，现有 `bpg-frpc` |
| FRP proxy | `cs-agent-dev-http` |
| 类型 | HTTP vhost；不要新增 frpc，不要配置 `type=https` |

`cs-agent-dev-http` 应注册的 ecommerce dev `customDomains`：

```text
cs-agent-dev.fcihome.com
api.ecommerce-cs-agent-dev.fcihome.com
admin.ecommerce-cs-agent-dev.fcihome.com
system-admin.ecommerce-cs-agent-dev.fcihome.com
```

外层 ai-agent Traefik 的 `frps_vhost` router 也必须包含这些 Host，并转发到 `erp_ai_agent_frps` 的 HTTP vhost 端口 `8081`。公网 HTTPS 由 ai-agent Traefik 终止，K3s 侧只需要注册 HTTP vhost；不要为这些域名额外注册 frpc `type=https`。

验证命令只记录结构，不输出密钥：

```bash
ssh ai-agent 'docker inspect erp_ai_agent_frps --format "{{json .Config.Labels}}"'
ssh ai-agent 'docker logs erp_ai_agent_frps --tail=300 2>&1 | grep -E "cs-agent-dev-http|system-admin.ecommerce-cs-agent-dev.fcihome.com"'
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get ingress,certificate,challenge,order
curl -fsS https://system-admin.ecommerce-cs-agent-dev.fcihome.com/health
```

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
| `LLM_BASE_URL` | 已写入 |
| `LLM_MODEL` | 已写入 |
| `SESSION_SECRET` | 已写入 |
| `JWT_SECRET` | 已写入 |
| `AGENT_API_TOKEN` | 已写入 |
| `OPEN_ERP_INTEGRATION_TOKEN` | 已写入 |
| `OPEN_ERP_BILLING_LEASE_SECRET` | 已写入 |
| `ADMIN_INITIAL_EMAIL` | 已写入 |
| `ADMIN_INITIAL_PASSWORD_HASH` | 已写入 |

模型凭据 Secret：`ecommerce-cs-agent-llm-provider`

| Key | 用途 |
| --- | --- |
| `api-key` | LLM Provider 连接与调用凭据 |

LLM cursor 签名 Secret：`ecommerce-cs-agent-llm-cursor`

| Key | 用途 |
| --- | --- |
| `signing-key` | 注入 `LLM_CURSOR_SIGNING_KEY`，用于配置版本、调用明细和发布记录 cursor 的 HMAC-SHA256 签名；至少 32 字节 |

该 Secret 由 `api.cursorSigningSecretRef{name,key}` 引用，与运行时 Secret 和 Provider 凭据 Secret 分离；namespace 是 Helm release namespace。仓库只保存 Secret 名与 key；真实随机值必须通过受控 Secret 渠道创建并轮换。所有 API replica 必须读取同一个至少 32 字节的 key，否则 cursor 会随机失效。轮换后已有 cursor 会失效并返回 422，调用方应从第一页重新查询；轮换发布记录只保存时间、Secret 引用和 rollout 结果，不保存 key 值。

模型凭据必须放在单独的 Secret 中，禁止复用 `ecommerce-cs-agent-runtime`。数据库/API 的 Provider 记录使用 `secret_ref{namespace,name,key}`；Helm allowlist 的 namespace 固定为 Pod 所在 namespace，并由 downward API 注入。该 Secret 只允许包含模型 Provider 所需凭据 key；不得包含 `DATABASE_URL`、`JWT_SECRET`、`SESSION_SECRET` 或其他运行时密钥。Helm 的 `api.secretAccess.allowedSecretRefs` 必须按 `(Secret name, key)` 配置允许的 `allowedOrigins`；每个 origin 必须是无用户信息、路径、查询或片段的精确 HTTPS origin。API ServiceAccount 的 Role 只授予这些专用 Secret 的 `get` 权限。dev 发布前需通过受控 Secret 渠道创建该专用 Secret，不在 values、文档、日志或聊天中记录凭据值。

API Deployment 的 `LLM_API_KEY` 通过 `secretKeyRef` 从 `api.runtimeLlmSecretRef` 指定的专用 Secret 与 key 注入，不写入 values 或渲染产物。该 `(name, key)` 必须同时存在于 `api.secretAccess.allowedSecretRefs`，且名称不得等于 `api.envFromSecret`；`ecommerce-cs-agent-runtime` 继续只通过 `envFrom` 提供非模型凭据运行配置。

`api.runtimeLlmSecretRef` 对应的凭据会在 API 启动时自动绑定当前 `LLM_BASE_URL` 的 origin；因此 values 中该 tuple 的 `allowedOrigins` 可为空。所有额外凭据 tuple 必须显式列出至少一个 origin，否则 Helm 渲染失败。连接测试只支持公网 HTTPS Provider：DNS 返回的全部 A/AAAA 地址都必须是公网地址，Kubernetes Service 域名、私网/回环/链路本地地址和发生 DNS 混合解析的目标均会被拒绝。验证后的 IP 会固定用于该次 TLS 连接，同时保留原始域名的 SNI 与 Host；Provider 重定向被禁用。内部 Provider 目前不受支持，不能通过扩大 allowlist 绕过该边界。

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

Provider 连接仅支持直连或无认证的 `http://` CONNECT 代理；不支持的代理协议或带凭据的代理配置会直接失败，不会退回普通 URL 客户端。读取 Kubernetes Secret 使用独立的集群 CA、ServiceAccount token 和直连 transport，不继承 Provider 代理、不跟随重定向且仅发起 GET。一次连接测试的 DNS、Secret 读取和 Provider 请求共享同一个 20 秒绝对截止时间。

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
OPEN_ERP_INTEGRATION_TOKEN=<from-secret>
OPEN_ERP_BILLING_LEASE_SECRET=<from-secret>
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
