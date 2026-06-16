# Development Readiness

本文列出下一步开发、测试和部署前的阻塞点。目标是让 Agent API、Admin Web、评测工具和 Deploy 项目之间的接口一次对齐，减少开发中断。

## 已确认可用

| 项目 | 状态 |
| --- | --- |
| k3s 集群 | `~/.kube/bpg-debian12-master-public.yaml` 可访问，`master`、`agent-0` Ready |
| Namespace | `ecommerce-cs-agent-dev` 已创建 |
| PostgreSQL | `postgres.ecommerce-cs-agent-dev.svc.cluster.local:5432` Ready |
| PostgreSQL extensions | `pgcrypto`、`vector` 已启用 |
| MinIO | `minio.ecommerce-cs-agent-dev.svc.cluster.local:9000` Ready |
| Object bucket | `ecommerce-cs-agent-dev` 已创建并验证上传 |
| Runtime Secret | `ecommerce-cs-agent-runtime` 已创建 |
| Registry pull | `ghcr-auth` 已创建 |
| Domains | API/Admin 域名已解析并通过 HTTPS 验证 |
| TLS | `cs-agent-dev-tls` Ready |
| API Deployment | `ecommerce-cs-agent-api` 已部署，`1/1 Running` |
| Admin Deployment | `ecommerce-cs-agent-admin` 已部署，`1/1 Running` |
| API Health | `https://api.ecommerce-cs-agent-dev.fcihome.com/health` 返回 `200` |
| Admin Health | `https://admin.ecommerce-cs-agent-dev.fcihome.com/health` 返回 `200` |
| Evaluation auth | live 评测已支持 `Authorization: Bearer <token>` |
| Public live eval | 公网 HTTPS quick suite `6/6 passed` |

## 已解除的环境卡点

以下外部信息和部署入口已由 Deploy 项目补齐：

| 项目 | 状态 |
| --- | --- |
| LLM provider | `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 已写入 runtime Secret |
| 初始管理员 | `ADMIN_INITIAL_EMAIL`、`ADMIN_INITIAL_PASSWORD_HASH` 已写入 runtime Secret |
| API 鉴权策略 | 第一版固定使用 `Authorization: Bearer AGENT_API_TOKEN` |
| 镜像发布规则 | 当前 tag 为 `dev-20260616-1459`；正式链路使用 GitHub Actions `Publish Images` 推 GHCR |
| Ingress 创建归属 | 应用 Helm chart 创建 API/Admin Ingress |
| 数据库 migration | `python -m ecommerce_cs_agent.db.cli migrate` 已通过 Helm hook 执行 |
| 出网代理 | API Pod 已注入 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` |

## 仍然卡业务完整度的内容

| 卡点 | 需要谁提供 | 解法 |
| --- | --- | --- |
| 真实 LLM 调用 | 后端 | 用 runtime Secret 中的 LLM 配置接入 provider，保留超时、重试、错误分类和审计 |
| LangGraph 编排 | 后端 | 把当前最小决策骨架替换为可 checkpoint 的图执行流程 |
| 数据持久化 | 后端 | 写入 `decision_record`、`decision_graph_checkpoint`、`audit_log` |
| Admin 登录 | 前后端 | 使用 Secret 中初始管理员引导创建用户，session 不落 Pod 内存 |
| 评测 worker | 开发/Deploy | 后续需要时补 CronJob/Job，而不是依赖本机手动运行 |

## 开发前必须固定的合同

### API Service

- 健康检查：`GET /health`
- 决策接口：`POST /v1/reply-decisions`
- 补上下文接口：使用 `context_requests[].endpoint` 返回的相对路径。
- 鉴权：`Authorization: Bearer <AGENT_API_TOKEN>`。
- 幂等：外部请求必须支持稳定 `request_id`；后续可增加 `Idempotency-Key` header。

### Admin Web

- Public / Admin 登录入口归 Agent 自己所有，不依赖 ERP 或外部系统登录态。
- Admin session 不保存到 Pod 内存；使用 PostgreSQL 或后续 Redis。
- 初始管理员通过 Secret 引导创建，不把初始密码写入仓库。

### Storage

- 结构化业务数据、LangGraph checkpoint、审计、知识、规则写 PostgreSQL。
- 原始文件、JSONL 归档、训练导出、评测报告写 MinIO。
- Pod 本地磁盘只做临时文件，不保存业务状态。

## 本地验证命令

```bash
.venv/bin/python -m pytest
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl get nodes
KUBECONFIG=~/.kube/bpg-debian12-master-public.yaml kubectl -n ecommerce-cs-agent-dev get pods,svc,ingress,secrets,pvc
```

业务 API 部署后再运行：

```bash
export TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com
export AGENT_API_TOKEN=<from-secret>
.venv/bin/python -m evals.cli run-suite --suite quick --target live
```

也可以显式传 token：

```bash
.venv/bin/python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL" --auth-token "$AGENT_API_TOKEN"
```

## 建议下一步一次性完成

1. 接真实 LLM client，并补单元测试覆盖成功、超时、鉴权失败、限流和 provider 错误。
2. 接 LangGraph 决策编排和 checkpoint，保持 `/v1/reply-decisions` 合同稳定。
3. 接 PostgreSQL 写入：决策记录、上下文请求、人工确认动作、审计日志。
4. 实现 Admin 初始化用户、登录和最小控制台。
5. 补评测 worker 的 CronJob/Job 镜像发布和部署流程。

## 已补齐的应用侧基础件

- Agent API FastAPI app：`ecommerce_cs_agent.api.app:app`
- API health endpoint：`GET /health`
- Reply decision endpoint：`POST /v1/reply-decisions`
- Context refill endpoint：`POST /v1/reply-decisions/{decision_id}/contexts/{context_type}`
- Bearer token 鉴权：读取 `AGENT_API_TOKEN`
- 数据库迁移命令：`python -m ecommerce_cs_agent.db.cli migrate`
- API 镜像文件：`Dockerfile.api`
- Admin 占位入口镜像文件：`admin-web/Dockerfile`
- Helm chart：`deploy/helm/ecommerce-cs-agent`
- 镜像发布 workflow：`.github/workflows/publish-images.yml`
- Dev Helm release：`ecommerce-cs-agent`
- Dev image tag：`dev-20260616-1459`
- Dev 公网 API：`https://api.ecommerce-cs-agent-dev.fcihome.com`
- Dev 公网 Admin：`https://admin.ecommerce-cs-agent-dev.fcihome.com`
