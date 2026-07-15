# 运行排障手册

本文面向 dev 环境的日常排障。它不替代架构设计或部署契约，只给出从症状到下一步检查的操作顺序。

相关文档：

- [Deployment](deployment.md)：dev 环境、域名、Secret、Registry 和部署验收。
- [Testing](testing.md)：本地测试、live eval 和发布门禁。
- [Security Local Files](security-local-files.md)：本地敏感文件、生成物和提交前检查。
- [Development Readiness](development-readiness.md)：第一版实现范围和验收命令。

## 1. 基础原则

- 不在日志、文档、聊天或 issue 中粘贴 `Authorization`、Cookie、token、完整 `DATABASE_URL`、LLM key、registry token、kubeconfig 或客户 payload。
- 先确认入口健康，再查应用，再查依赖，最后查 GitOps / 集群。
- `reports/evals/` 是本地生成物，默认不提交。
- 如果排查需要真实 Secret，只从 GitHub Secrets、Kubernetes Secrets 或批准的 Secret Manager 获取，并在本地 shell 临时注入。

## 2. `/health` 失败

先确认公网入口：

```bash
curl -i https://api.ecommerce-cs-agent-dev.fcihome.com/health
curl -i https://admin.ecommerce-cs-agent-dev.fcihome.com/health
curl -i https://system-admin.ecommerce-cs-agent-dev.fcihome.com/health
```

常见分支：

| 现象 | 下一步 |
| --- | --- |
| DNS 无法解析 | 检查域名解析是否指向当前 Ingress 公网入口。 |
| TLS 证书错误 | 检查 cert-manager Certificate、ClusterIssuer 和 Ingress host。 |
| 404 | 检查 Ingress rule、Service name、应用 path 是否一致。 |
| 502 / 503 | 检查 Pod readiness、Service selector、容器端口。 |
| 500 | 查应用日志和运行时环境变量。 |
| 连接超时 | 检查公网入口、FRP/Traefik、NetworkPolicy 或集群节点状态。 |

公网 FRP/Traefik 快速判断：

- `system-admin.ecommerce-cs-agent-dev.fcihome.com` 返回外层 `404` 时，优先检查 ai-agent 上 `erp_ai_agent_frps` 的 Traefik `frps_vhost.rule` 是否包含该 Host。
- `frps` 日志必须出现 `cs-agent-dev-http` listen for host `system-admin.ecommerce-cs-agent-dev.fcihome.com`；如果没有，检查 K3s `frp-system/bpg-frpc` 的 `cs-agent-dev-http` customDomains。
- K8s Ingress 已包含 host 但公网仍 `404`，通常是外层 FRP/Traefik 路由未放行，或 K3s frpc customDomains 未注册。
- `system-admin.ecommerce-cs-agent-dev.fcihome.com` 使用现有 `cs-agent-dev-http` HTTP vhost；不要新建 frpc，不要配置 `type=https`。

参考命令：

```bash
ssh ai-agent 'docker inspect erp_ai_agent_frps --format "{{json .Config.Labels}}"'
ssh ai-agent 'docker logs erp_ai_agent_frps --tail=300 2>&1 | grep -E "cs-agent-dev-http|system-admin.ecommerce-cs-agent-dev.fcihome.com"'
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get ingress,certificate,challenge,order
```

Admin 入口排查额外检查：

- `admin.ecommerce-cs-agent-dev.fcihome.com` 只能承载公开宣传页、客户登录页和客户后台；如果左侧导航出现“系统后台”入口，应按路由守卫或构建错误处理。
- `system-admin.ecommerce-cs-agent-dev.fcihome.com` 必须使用系统后台专用登录页和 `agent_system_admin_session`；如果客户后台 cookie 能进入系统后台，应按高优先级权限隔离缺陷处理。

集群侧检查命令：

```bash
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get pods,svc,ingress
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev describe ingress
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev logs deploy/ecommerce-cs-agent-api --tail=100
```

输出日志前先确认没有 token、Cookie、完整数据库 URL 或客户数据。

## 3. live eval 失败

标准命令：

```bash
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com \
  AGENT_API_TOKEN=<from-secret> \
  python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

排查顺序：

| 现象 | 含义 | 下一步 |
| --- | --- | --- |
| `FAIL health` | API 入口不可用或返回非 2xx。 | 先按 `/health` 失败排查。 |
| `status=401` | 未传 token、token 错误或服务端鉴权配置不一致。 | 确认 `AGENT_API_TOKEN` 从运行时 Secret 临时注入；不要打印 token。 |
| `status=403` | token 有效但没有租户 / 店铺 / 接口权限。 | 检查 token 授权范围与请求里的 `tenant_id`、`store_id`。 |
| `status=404` | `/v1/reply-decisions` 路由未部署或 Ingress 转发错误。 | 检查当前镜像版本和 API 路由实现。 |
| `status=422` | 请求 schema 与 OpenAPI / 服务端校验不一致。 | 对照 `docs/openapi.yaml` 和 eval 请求体。 |
| `status=500` | 服务端运行时错误。 | 查应用日志、DB、LLM、配置。 |
| `network failure` | 网络超时、DNS、TLS 或代理问题。 | 检查本地网络、代理和 `TARGET_BASE_URL`。 |

`evals.cli` 只输出 HTTP 状态、`decision_id`、`action`、`decision_status` 摘要，不应输出 token 或完整 Authorization header。

## 4. HTTP 状态码定位

| 状态码 | 常见原因 | 下一步 |
| --- | --- | --- |
| 400 | 请求格式非法或 JSON 无法解析。 | 检查请求体和 `Content-Type`。 |
| 401 | 缺少认证或认证无效。 | 检查 token/session 注入，不打印明文。 |
| 403 | 认证有效但权限不足。 | 检查租户、店铺、角色、客户 / 系统 Admin host、Cookie 名和 API 鉴权域。 |
| 404 | 路由不存在或资源不存在。 | 检查部署版本、OpenAPI path、Ingress path。 |
| 409 | 幂等冲突、版本冲突或重复动作。 | 检查 `request_id`、`idempotency_key`、资源版本。 |
| 422 | 字段校验失败或缺少审计原因。 | 对照 OpenAPI schema 和业务错误 code。 |
| 429 | 限流。 | 检查 token、租户、IP 或全局限流策略。 |
| 500 | 未预期服务错误。 | 查 trace_id、应用日志和依赖状态。 |

## 5. 数据库连接失败

检查方向：

- `DATABASE_URL` 是否从 `ecommerce-cs-agent-runtime` 注入。
- PostgreSQL Service 是否为 `postgres.ecommerce-cs-agent-dev.svc.cluster.local:5432`。
- 数据库、用户和 SSL mode 是否与 [Deployment](deployment.md) 一致。
- `pgcrypto` 和 `vector` 扩展是否存在。
- `schema_migration` 是否有当前版本记录。

示例检查：

```bash
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get secret ecommerce-cs-agent-runtime
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get svc postgres
```

不要把 Secret 内容解码后贴到聊天或文档。

## 6. LLM 或代理失败

常见原因：

- runtime 中的 `LLM_BASE_URL`、`LLM_MODEL` 未注入，或专用 `ecommerce-cs-agent-llm-provider` Secret 的 `api-key` 未通过 `secretKeyRef` 注入为 `LLM_API_KEY`。
- Helm `api.runtimeLlmSecretRef` 与 `api.secretAccess.allowedSecretRefs` 的 `(name, key)` 不一致，或错误复用了 `api.envFromSecret`。
- 额外 Secret tuple 未配置精确的公网 HTTPS `allowedOrigins`，或请求 origin 与该 tuple 的绑定不一致；runtime tuple 会自动绑定当前 `LLM_BASE_URL`。
- API ServiceAccount 的 namespaced Role 未对专用模型 Secret 授予精确的 `secrets/get/resourceNames` 权限。
- API Pod 代理配置错误。
- `NO_PROXY` 未包含 `.svc`、`.cluster.local`、PostgreSQL 或 MinIO 内网域名。
- Provider DNS 包含私网、回环、链路本地或 Kubernetes 地址，或同一主机名混合返回公网与非公网地址。
- Provider 返回重定向，或代理不是受支持的无认证 HTTP CONNECT 代理。
- LLM provider 超时或返回非 2xx。

检查：

```bash
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev describe deploy ecommerce-cs-agent-api
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev logs deploy/ecommerce-cs-agent-api --tail=100
```

检查 Deployment 的 `LLM_API_KEY.valueFrom.secretKeyRef` 是否指向专用 Secret，并检查 Role 的 `resourceNames` 是否包含相同 Secret 名。不要要求或恢复 `ecommerce-cs-agent-runtime` 中的 `LLM_API_KEY`，也不要输出 Secret 数据、环境变量值或解码结果。

检查 `allowedOrigins` 时只核对 origin 和 Secret/key 名称，不要读取凭据值。Provider 连接测试要求所有 DNS 结果均为公网地址，并在一次请求内固定已验证 IP；内部 Provider、重定向和 DNS 混合解析属于预期拒绝。DNS 使用进程级固定 daemon worker 与有界 outstanding 队列，容量耗尽会快速返回超时，不会为每个请求创建线程。Kubernetes Secret 读取要求 `KUBERNETES_SERVICE_HOST` 是 IP literal，TCP 固定连接该 IP，TLS 使用受信 `kubernetes.default.svc` 名称和集群 CA，且不使用业务 Pod 的 Provider 代理。HTTP CONNECT 代理也先通过同一有界解析器解析并固定 IP，不把代理主机名交给 `create_connection`。DNS、Secret 读取和 Provider 请求共享 20 秒绝对截止时间；TCP、CONNECT、TLS、请求头和分块响应体每阶段都只使用剩余时间，socket 到期 guard 会关闭仍在慢速读写的连接，任一阶段耗尽后不会继续下一阶段。

通过 `POST /v1/system-admin/llm/providers` 创建 Provider 时，非法 `secret_ref` 返回 422 `validation_error`，详情定位到 `secret_ref.namespace`、`secret_ref.name` 或 `secret_ref.key`。`PATCH /v1/system-admin/llm/providers/{provider_id}` 不接受 `secret_ref`：Provider 端点与 Secret 引用不可原地替换，提交该字段返回 422 `validation_error` / `extra_forbidden`，需要更换引用时应按现有安全流程创建新 Provider。只有绕过 Pydantic API 模型、直接调用 LLM governance service create/update 时，非法引用才使用 422 `invalid_secret_ref`。三条路径都要求 namespace 是最长 63 字符且不含点的 DNS-1123 label，Secret name 是最长 253 字符且每段最长 63 字符的 DNS-1123 subdomain，key 是最长 253 字符的 Kubernetes data key；首尾空白或换行都必须拒绝，且不得写入持久化状态。

日志中如包含 provider 请求头、key、prompt 原文或客户 payload，先脱敏再分享。

若配置版本、调用明细或发布记录翻页返回 422 `invalid_cursor`：

1. 确认调用方没有把 cursor 用于不同资源、组织或筛选；cursor 只对原规范化 scope 有效。
2. 确认 `LLM_CURSOR_SIGNING_KEY` 来自独立 `api.cursorSigningSecretRef`，与 runtime/Provider Secret 不同，且所有 API replica 指向同一 Secret name/key。
3. 若刚完成签名 key 轮换，旧 cursor 按设计失效；不要恢复旧 key 或输出 cursor payload，直接从第一页重新查询。
4. 轮换后观察所有 API Pod rollout 完成，再做跨 replica 连续翻页 smoke；发布记录只写 Secret 引用和验证结果，不写 key 值或原始 cursor。

## 7. K8s rollout 失败

检查顺序：

```bash
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev rollout status deploy/ecommerce-cs-agent-api
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get pods
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev describe pod <pod-name>
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev logs <pod-name> --tail=100
```

| 现象 | 下一步 |
| --- | --- |
| `ImagePullBackOff` | 检查 image tag、Registry、`imagePullSecrets`、阿里云/GHCR 凭据。 |
| `CrashLoopBackOff` | 查容器日志、启动命令、环境变量、数据库连接。 |
| readiness 不通过 | 检查 `/health` 路径、端口、启动耗时和依赖。 |
| 旧版本仍在服务 | 检查 GitOps image tag、Flux reconcile、Helm release revision。 |

release gate 会在 HelmRelease 失败、回滚或超时状态下，对新的 GitOps commit 执行一次受控 `resetAt` + `requestedAt`，并记录原始 HelmRelease condition；普通 Progressing 状态只触发常规 reconcile。若 Flux、Helm、目标 image tag、rollout 或 migration 未通过，release gate 会采集 HelmRelease JSON、namespace events 和相关 API/Admin Pod 日志摘要后停止，不继续运行 health / quick live eval。人工接手时先看 release gate artifact 的前置失败项，不要用旧版本 `/health` 成功替代目标版本验收。

## 8. 何时转到 GitOps / Deploy 仓库

以下问题通常不应只在应用仓库修：

- Ingress host、TLS、Certificate、ClusterIssuer。
- Helm values、Deployment、Service、Secret 引用。
- Flux reconcile、HelmRelease、Kustomization。
- imagePullSecrets、registry 凭据、namespace。
- PostgreSQL / MinIO StatefulSet、PVC、Service。

应用仓库需要提供的交接信息：

- 应用 commit 和 image tag。
- 需要的 env key 和 Secret key 名称。
- 健康检查路径。
- live eval 命令和失败摘要。
- 不含敏感值的日志片段或 trace_id。
