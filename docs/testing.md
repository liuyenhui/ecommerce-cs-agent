# 测试说明

本文集中说明当前仓库可直接运行的测试入口、后续测试分层、目录规划、OpenAPI 契约测试口径和评测门禁。第一版需求到正向、拒绝、自动化与线上证据的逐项入口见 [第一版需求测试矩阵](requirements-test-matrix.md)。它不是新的架构来源，只把 [Development Readiness](development-readiness.md)、[Automated Blind Testing Design](superpowers/specs/2026-06-14-automated-blind-testing-design.md)、[OpenAPI Contract](openapi.yaml) 和 [Deployment](deployment.md) 中的测试要求收敛成执行说明。

## 1. 当前可运行测试

当前仓库已把 Python、Admin Web、OpenAPI、Helm 和部署边界测试纳入项目依赖。仓库根目录优先使用 `$PROJECT_ROOT/.venv/bin/python`；隔离 worktree 没有 `.venv` 时，应激活已安装本项目 dev 依赖的 Python 环境并使用 `python -m pytest`，工作目录仍保持在当前 worktree。不得在项目文档中硬编码个人用户目录下的虚拟环境路径。

本地全量 Python 测试：

```bash
.venv/bin/python -m pytest tests -q
```

文档与 OpenAPI 契约快测：

```bash
.venv/bin/pytest tests/contract/test_markdown_links.py tests/contract/test_openapi_contract.py -q
```

Admin Web 测试与客户/系统双构建：

```bash
npm --prefix admin-web test
npm --prefix admin-web run build:customer
npm --prefix admin-web run build:system
```

本机 Admin 凭据 helper 的确定性测试不访问 live 服务，也不需要安装 Admin Web 依赖：

```bash
npm run test:admin-credentials
```

Customer Admin 与 System Admin 的本机 live 测试账号只保存在仓库外 `~/.config/ecommerce-cs-agent/admin-test-credentials.env`。需要生成两套隔离的 Playwright `storageState` 时，显式使用该安全文件并禁用 Kubernetes Secret 回退：

```bash
AUTH_STATE_DIR="$(mktemp -d /tmp/ecommerce-admin-auth-XXXXXX)"
chmod 700 "$AUTH_STATE_DIR"
node scripts/admin_web_login_state.mjs \
  --credentials-file "$HOME/.config/ecommerce-cs-agent/admin-test-credentials.env" \
  --skip-kubectl \
  --output-dir "$AUTH_STATE_DIR"
# 完成本机 UI 测试后：
rm -rf "$AUTH_STATE_DIR"
```

该命令不得输出密码、Cookie 或认证响应正文；生成目录必须保持在 `/tmp/ecommerce-admin-auth-*`，测试结束后必须删除。凭据文件的 owner、`0700` 父目录、`0600` 文件及 symlink / 仓库内路径拒绝规则见 [本地敏感文件与生成物管理](security-local-files.md)。

Helm 与部署边界：

```bash
helm lint deploy/helm/ecommerce-cs-agent -f deploy/helm/ecommerce-cs-agent/values-dev.yaml
helm template ecommerce-cs-agent deploy/helm/ecommerce-cs-agent -n ecommerce-cs-agent-dev -f deploy/helm/ecommerce-cs-agent/values-dev.yaml >/tmp/ecommerce-cs-agent-rendered.yaml
.venv/bin/pytest tests/deploy/test_deploy_artifacts.py tests/api/test_admin_boundaries.py tests/api/test_system_admin_v1.py tests/api/test_system_admin_llm_v1.py tests/services/test_llm_governance.py tests/services/test_llm_governance_adapters.py tests/db/test_migrations.py -q
rm -f /tmp/ecommerce-cs-agent-rendered.yaml
```

真实 PostgreSQL 集成是可选本地检查，必须指向隔离测试库，并通过环境变量注入；命令与日志不得打印 DSN 或 Secret：

```bash
APP_ENV=test TEST_DATABASE_URL=<from-secret> .venv/bin/pytest tests/db/test_migrations_postgres.py tests/services/test_llm_governance.py -q
```

未设置 `TEST_DATABASE_URL` 时对应 PostgreSQL 用例按测试标记跳过，不得为了消除 skip 使用生产数据库。最小 eval CLI 仍可运行 `python -m unittest tests.evals.test_live_cli -v` 和 `python -m evals.cli --help`。

## 2. 测试分层

| 层级 | 目标 | 运行位置 | 依赖 |
| --- | --- | --- | --- |
| `unit` | 校验纯函数、状态转换、评分工具、脱敏工具和小型策略判断。 | 本地、PR | 不依赖真实服务和真实 LLM。 |
| `contract` | 校验 OpenAPI、请求/响应 schema、枚举、必需字段、错误结构和权限边界。 | 本地、PR | 可静态解析 `docs/openapi.yaml`，也可对 mock app 发请求。 |
| `integration` | 校验 API、状态流、typed context refill、幂等、持久化和外部动作结果回填。 | PR、staging | 使用隔离数据库、mock LLM、mock 外部系统。 |
| `policy` | 校验规则闸门、红线行为、风险分级和自动回复边界。 | 本地、PR、发布前 | 使用确定性 fixture，不依赖随机生成。 |
| `admin-audit` | 校验客户 Admin / 系统 Admin 的权限、配置变更和审计日志。 | PR、发布前 | 需要 Admin session fixture 和审计断言。 |
| `evals` | 校验业务问答质量、盲测、红线、回归集和基线对比。 | 每日、发布前 | mock eval 可不依赖真实 token；live eval 需要真实目标环境和 Secret。 |

PR 阶段只跑确定性测试，不跑大规模 LLM 盲测。LLM 生成用例、语义 judge 和大批量盲测应放在每日任务、合并前抽检或发布前门禁中，避免 PR 因随机性、耗时或供应商波动变得不稳定。

## 3. 目录规划

后续测试目录按分层收敛：

```text
tests/
  unit/
  contract/
  integration/
  policy/
  evals/
evals/
  cases/
    generated/
    regression/
reports/
  evals/
```

目录职责：

- `tests/unit`：纯单元测试，不访问网络，不读取真实 Secret。
- `tests/contract`：OpenAPI 静态契约、API schema、错误结构和权限契约。
- `tests/integration`：跨 API、数据库、状态流和 typed context refill 的确定性集成测试。
- `tests/policy`：红线、规则闸门、自动回复安全边界和动作确认要求。
- `tests/evals`：评测 CLI、runner、报告、脱敏和本地测试 server。
- `evals/cases/generated`：LLM 自动生成的盲测用例，默认不作为稳定回归来源。
- `evals/cases/regression`：人工确认后的固定回归用例，必须稳定可复现。
- `reports/evals`：每日、发布前、baseline 对比和失败分类报告。

生成类数据和报告不能包含真实买家隐私、真实 token、请求头、cookie 或 Secret 明文。

## 4. OpenAPI Contract Test

OpenAPI 契约测试应以 `docs/openapi.yaml` 为源文件，不依赖服务启动即可完成基础检查。

必做断言：

- 解析 `docs/openapi.yaml`，确认 YAML 可被测试依赖正常加载。
- 遍历所有本地 `$ref`，只允许 `#/...` 形式的本地引用；每个引用都必须能在文档内解析到目标节点。
- 检查关键 schema 的 `required` 字段存在且类型合理，例如决策请求、决策响应、context refill、action result、feedback、trace、Admin 登录和 audit log。
- 检查第一版必需 paths 存在，并至少包含对应 HTTP method、`operationId`、认证声明、请求体和主要响应。

第一版最小必需 paths：

| 路径 | 目的 |
| --- | --- |
| `/v1/reply-decisions` | 外部客服系统同步决策入口。 |
| `/v1/reply-decisions/{decision_id}/contexts/products` | 商品上下文回填。 |
| `/v1/reply-decisions/{decision_id}/contexts/orders` | 订单上下文回填。 |
| `/v1/reply-decisions/{decision_id}/contexts/logistics` | 物流上下文回填。 |
| `/v1/reply-decisions/{decision_id}/contexts/rules` | 规则上下文回填。 |
| `/v1/reply-decisions/{decision_id}/actions/results` | 外部动作执行结果回填。 |
| `/v1/message-traces/{decision_id}` | 单条决策 trace 查询。 |
| `/v1/feedback/human-replies` | 人工回复和采用结果回传。 |
| `/v1/admin/auth/login`、`/v1/admin/auth/logout`、`/v1/admin/auth/me` | 客户 Admin 登录态。 |
| `/v1/admin/audit-logs` | 客户 Admin 审计查询。 |
| `/v1/product-content/products`、`/v1/product-content/assets`、`/v1/product-content/price-snapshots` | 商品资料、资产和价格快照。 |
| `/v1/system-admin/auth/login`、`/v1/system-admin/auth/logout`、`/v1/system-admin/auth/me` | 系统 Admin 登录态。 |
| `/v1/system-admin/dashboard-summary`、`/v1/system-admin/organizations`、`/v1/system-admin/stores`、`/v1/system-admin/readiness/stores`、`/v1/system-admin/message-traces`、`/v1/system-admin/tasks`、`/v1/system-admin/audit-logs`、`/v1/system-admin/health` | 系统运营、分页、排障、任务、审计和健康检查。 |
| `/v1/system-admin/llm/providers*`、`/v1/system-admin/llm/config-versions*`、`/v1/system-admin/llm/releases` | Provider、Secret 引用、配置版本、评测绑定、真实发布记录和回滚。 |
| `/v1/system-admin/llm/usage/summary`、`/v1/system-admin/llm/usage/timeseries`、`/v1/system-admin/llm/usage/breakdown`、`/v1/system-admin/llm/usage/invocations` | 真实用量、混合币种和脱敏调用明细。 |
| Customer / System Admin Web split | `admin.ecommerce-cs-agent-dev.fcihome.com` 不展示系统后台入口；`system-admin.ecommerce-cs-agent-dev.fcihome.com` 使用系统后台专用登录页、Cookie 和路由守卫。 |

后续新增、重命名或删除 OpenAPI path 时，必须同步更新 contract test 的必需路径清单。

System Admin / LLM 治理边界回归还必须覆盖：

- `tests/api/test_admin_boundaries.py`：用 Python AST 检查 InMemory Admin 构造器默认空、`create_app` 不注入业务 seed，development/production 缺数据库或必需 Secret fail fast，Customer/System session 互不接受。
- `admin-web/scripts/admin-boundary.test.mjs`：检查九页前端不含 demo fallback，Provider 编辑器只接受真实 DOM 中的 `namespace/name/key` 引用字段，并通过 TypeScript AST 拒绝 raw credential 字段；认证登录密码是唯一受控例外。
- `tests/services/test_llm_governance.py`、`tests/api/test_system_admin_llm_v1.py` 和 `tests/contract/test_openapi_contract.py`：检查版本、发布记录、invocation cursor 的 HMAC 签名、版本号、排他边界、资源类型和规范化 scope；无签名、篡改、跨组织/跨筛选/跨资源 cursor 返回 422。
- `tests/api/test_system_admin_llm_v1.py`、`tests/services/test_llm_governance.py`、`tests/deploy/test_deploy_artifacts.py` 与 `tests/services/test_llm_governance_adapters.py`：检查 API/Pydantic、直接 service create/update、Helm 与 runtime adapter 一致拒绝非法 Secret 引用；namespace 使用最长 63 字符且无点的 DNS-1123 label，name 使用最长 253 字符且每段最长 63 字符的 DNS-1123 subdomain，key 使用最长 253 字符的 Kubernetes data key；并覆盖 Secret 分离、tuple 去重、origin allowlist、固定 IP/DNS rebinding/redirect/统一 deadline 门禁。
- `tests/api/test_system_admin_v1.py` 与 `admin-web/system-admin/src/system-admin.test.tsx`：检查真实分页 total、`action_prefix`、任务 `retryable`、九项菜单、64px 折叠、移动抽屉、真实空态/partial/error、组织和筛选切换时中止旧 cursor 请求。

## 5. Mock 与 Live Eval

`mock` eval 用于本地、PR 和确定性回归：

- 不依赖真实 `TARGET_BASE_URL`。
- 不依赖真实 `AGENT_API_TOKEN`。
- 使用 mock LLM、mock 外部系统和固定 fixture。
- 适合验证 schema、状态流、policy gate、动作规划和审计逻辑。
- 输出可以包含测试请求摘要，但仍必须脱敏，不打印 Secret、Authorization、cookie 或真实用户数据。

`live` eval 用于已部署环境、每日检查和发布前验证：

- 需要 `TARGET_BASE_URL` 指向真实 API。
- 需要 `AGENT_API_TOKEN` 从 Secret 或安全环境变量注入。
- 当前 quick suite 会检查 `GET /health`，再发送最小 `POST /v1/reply-decisions` 请求。
- 输出只允许打印 pass/fail、HTTP 状态、`decision_id`、`action`、`decision_status` 和脱敏摘要。
- 失败日志必须避免打印 token、完整 Authorization header、cookie、数据库 URL、LLM key 或客户原始数据。

live quick eval 示例：

```bash
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com
AGENT_API_TOKEN=<from-secret> python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

预期结果：

```text
PASS health status=200
PASS reply-decisions status=200 decision_id=<redacted-or-test-id> action=<action> decision_status=<status>
quick suite PASS target=live url=https://api.ecommerce-cs-agent-dev.fcihome.com
```

## 6. PR、每日与发布前门禁

### 6.1 PR 门禁

PR 门禁只运行确定性测试，目标是快速阻断接口、权限、状态流和规则闸门问题：

```bash
python -m unittest tests.evals.test_live_cli -v
python -m evals.cli --help
```

Admin Web 当前必须运行：

```bash
npm --prefix admin-web test
npm --prefix admin-web run build:customer
npm --prefix admin-web run build:system
```

其中 route guard / E2E 用例至少覆盖：客户后台不出现系统后台入口；客户 Admin session 访问系统后台返回未登录或无权限；系统 Admin session 不能伪装客户用户调用客户 Admin API。

Python 当前必须运行：

```bash
.venv/bin/python -m pytest tests -q
```

PR 不跑大规模 LLM 盲测。若需要在 PR 上抽检 eval，只能使用小规模、固定 seed、可复现的 mock eval。

### 6.2 每日检查

每日任务用于发现业务质量波动，应包含：

- 盲测：LLM 生成买家问法、干扰上下文和隐藏期望。
- 红线：跨租户泄露、无有效价格自动报价、高风险自动回复、越权动作、trace 缺失。
- 回归：运行 `evals/cases/regression` 中人工确认的稳定失败样例。
- baseline 对比：与上一稳定版本对比通过率、平均分、红线数、`handoff` / `context_request` / `action_request` 比例。

每日报告输出到 `reports/evals`，失败用例要带 `decision_id`、trace 摘要、失败分类、输入引用和脱敏评分理由。

### 6.3 发布前门禁

发布前必须包含：

- 快测全量。
- OpenAPI contract test。
- 固定回归集。
- 盲测核心集。
- 红线集。
- baseline 对比。

红线失败一票否决。核心通过率、语义平均分或动作比例相对 baseline 异常波动时，需要人工确认后才能继续发布。

## 7. 失败分类

所有失败结果必须归入一个主分类，便于报告聚合和缺陷修复：

| 分类 | 含义 |
| --- | --- |
| `contract_failure` | OpenAPI、HTTP 状态、schema、必需字段、枚举或响应结构不符合契约。 |
| `state_flow_failure` | 决策状态机、LangGraph 节点、checkpoint、interrupt/resume 或状态流转不符合预期。 |
| `permission_failure` | 权限、租户隔离、店铺隔离、Admin session 或 API token 边界错误。 |
| `context_failure` | 上下文请求、typed context refill、上下文选择、聚合或缺失判断错误。 |
| `policy_gate_failure` | 规则闸门、风险分级、红线阻断或自动回复安全边界错误。 |
| `action_planning_failure` | `action_request` 类型、payload、幂等键、人工确认或动作能力约束错误。 |
| `audit_failure` | `decision_id`、trace、决策记录、Admin audit log 或评测证据缺失。 |
| `runtime_failure` | 服务不可用、网络超时、未捕获异常、CLI 崩溃、依赖缺失或测试环境故障。 |

如果失败既像测试数据问题又像系统问题，先归入最接近的系统分类，并在报告中标记需要人工复核；不能用“评测不确定”掩盖红线失败。

## 8. 验证命令和预期结果

当前最小验证：

```bash
python -m unittest tests.evals.test_live_cli -v
```

预期：

- `test_quick_live_suite_passes_and_summarizes_decision` 为 `ok`。
- `test_bearer_token_is_sent_but_not_printed` 为 `ok`。
- `test_runtime_failure_returns_nonzero_without_traceback` 为 `ok`。
- 最终输出 `Ran 3 tests` 和 `OK`。

CLI 入口验证：

```bash
python -m evals.cli --help
```

预期：

- 命令退出码为 0。
- 输出包含 `usage: python -m evals.cli`。
- 输出包含 `run-suite`。

live quick eval 验证：

```bash
TARGET_BASE_URL=https://api.ecommerce-cs-agent-dev.fcihome.com
AGENT_API_TOKEN=<from-secret> python -m evals.cli run-suite --suite quick --target live --target-url "$TARGET_BASE_URL"
```

预期：

- `/health` 返回 2xx，输出 `PASS health status=200` 或对应 2xx 状态。
- `/v1/reply-decisions` 返回 2xx 且包含 `decision_id`。
- 输出 `quick suite PASS target=live`。
- stdout、stderr 不包含 `AGENT_API_TOKEN` 明文、不包含完整 Authorization header。

OpenAPI contract test 当前命令为：

```bash
.venv/bin/pytest tests/contract/test_markdown_links.py tests/contract/test_openapi_contract.py -q
```

预期：

- `docs/openapi.yaml` 可解析。
- 所有本地 `$ref` 可解析。
- 第一版必需 paths 全部存在。
- schema 必需字段、认证边界和错误结构断言全部通过。
