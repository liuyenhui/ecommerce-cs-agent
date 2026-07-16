# 本地敏感文件与生成物管理

本文说明本地开发过程中敏感文件、临时 Secret 和生成物的管理规则。本文是 [AGENTS](../AGENTS.md) 中 Public Repository Safety 的本地补充，不替代仓库公开安全要求；提交、推送和发布时仍必须遵守 Public Repository Safety、[Deployment](deployment.md) 和 [开发就绪说明](development-readiness.md) 中的安全约束。

`.gitignore` 由主会话统一更新。本文只说明规则，不作为 `.gitignore` 的替代。

## 1. 不得提交的敏感文件和内容

以下文件或内容不得进入 Git 索引、提交、评审截图、公开 artifact 或聊天记录：

| 类型 | 示例 |
| --- | --- |
| 本地环境文件 | `.env`、`*.env` |
| Kubernetes 凭据 | kubeconfig、集群 context、ServiceAccount token |
| 云厂商凭据 | access key、secret key、cloud credentials |
| API 密钥 | 外部平台 API key、Webhook secret、系统访问 token |
| 会话与签名密钥 | `JWT_SECRET`、`SESSION_SECRET`、cookie/session signing secret |
| LLM 凭据 | `LLM_API_KEY`、模型供应商 key、代理网关 token |
| 镜像仓库凭据 | registry token、`.dockerconfigjson`、GHCR/阿里云 Registry 密码 |
| 证书私钥 | private certificates、`BEGIN PRIVATE KEY`、私有 CA key |
| 客户数据 | 客户文件、客户业务导出、JSONL 导出、带真实订单/买家/聊天内容的数据集 |

文档可以记录 Secret 名称、Kubernetes Secret 名称、GitHub Secrets key 和读取路径，但不能记录明文值。需要示例时使用 `<from-secret>`、`<redacted>` 或本地假值。

## 2. 生成物不提交

以下本地生成物默认不得提交：

| 路径 / 模式 | 说明 |
| --- | --- |
| `__pycache__/` | Python 字节码缓存目录 |
| `*.pyc` | Python 字节码文件 |
| `*.egg-info/` | Python 包构建元数据 |
| `.pytest_cache/` | pytest 本地缓存 |
| `.venv/` | 本地虚拟环境 |
| `reports/evals/` | 本地评测输出、原始 trace、失败样本和中间报告 |
| `reports/*.png` | 本地截图或图表输出 |

`reports/*.png` 只有在明确作为审阅 artifact、已经脱敏、且评审范围要求提交时，才允许单独确认后加入索引。包含 token、请求头、cookie、客户数据、真实订单、真实买家信息或未脱敏错误日志的截图不得提交。

## 3. 本地 `.env` 使用规则

本地 `.env` 只用于开发占位值，或从 GitHub Secrets、Kubernetes Secrets、外部 Secret Manager 临时注入后的本机运行配置。不要把真实值复制到文档、Issue、PR、聊天记录、终端贴图或日志输出中。

调试时如果需要确认变量是否存在，只输出变量名、来源或是否为空，不输出值。例如只记录 `LLM_API_KEY 已从 Secret 注入`，不要记录 key 内容。

## 4. 本机 Admin live 测试凭据

Customer Admin 与 System Admin 的本机 live 测试账号只能保存在 `~/.config/ecommerce-cs-agent/admin-test-credentials.env`。该路径必须位于仓库外，父目录归当前用户所有且权限为 `0700`，文件归当前用户所有且权限为 `0600`；父目录和文件都不得是符号链接，也不得把文件当作 shell 脚本执行。

文件只允许包含以下四个 key，且四项都必须存在：

```text
CUSTOMER_ADMIN_EMAIL
CUSTOMER_ADMIN_PASSWORD
SYSTEM_ADMIN_EMAIL
SYSTEM_ADMIN_PASSWORD
```

本文不记录任何值。可复用的明文密码和完整的本机四 key 便利文件都只允许留在本机，不得发送到聊天、加入 Git、上传云存储，或复制到 Kubernetes、Helm values、Docker build context / 镜像。运行时初始邮箱与密码哈希仍按项目规则通过批准的 Kubernetes Secret key 管理，例如 `ADMIN_INITIAL_EMAIL`、`ADMIN_INITIAL_PASSWORD_HASH`、`SYSTEM_ADMIN_INITIAL_EMAIL` 和 `SYSTEM_ADMIN_INITIAL_PASSWORD_HASH`；本机文件不替代运行时 Secret，本流程也不得把明文密码放入 Kubernetes Secret。首次使用时只创建空模板，再通过批准的本机安全渠道填写：

```bash
node scripts/admin_web_login_state.mjs --init-credentials-file
```

登录测试生成的 Playwright `storageState` 强制直接写入 `/tmp/ecommerce-admin-auth-*`，输出目录必须归当前用户所有、权限保持 `0700` 且不得是符号链接，状态文件权限保持 `0600`。双登录任一步失败时脚本清理本次事务已生成的状态文件；测试结束后也必须删除对应目录，不得提交、分享或长期保存其中的 Cookie。

## 5. 提交前检查

提交前至少执行以下检查，并人工确认 staged diff 中没有 Secret、客户数据或无关生成物：

```bash
git status --short
git diff --cached
git diff --cached | rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET"
```

检查重点：

- `git status --short` 中不应出现 `.env`、`*.env`、`.venv/`、`__pycache__/`、`.pytest_cache/`、`reports/evals/` 或未确认的 `reports/*.png`。
- `git diff --cached` 中不应出现 Secret 明文、客户数据、请求头、cookie、kubeconfig、registry 凭据或私钥内容。
- 敏感模式 `rg` 命中后必须逐条确认。即使是占位值，也应判断是否容易被误认为真实 Secret。

## 6. 发现误加入 Secret 的处理

如果发现 Secret、客户数据或敏感生成物已经加入索引：

1. 立即停止提交和推送。
2. 将文件或内容移出索引，只保留本地需要的副本。
3. 轮换已经暴露或可能暴露的 Secret、token、证书或密码。
4. 不要在聊天、Issue、PR 评论或日志中贴出 Secret 明文。
5. 重新运行提交前检查，确认 staged diff 只包含允许提交的内容。

如果 Secret 已经被推送到远端，按泄露处理：轮换凭据、评估访问日志、清理历史时避免再次公开明文，并在安全渠道同步处理进展。
