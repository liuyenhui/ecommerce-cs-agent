# 测试说明

本文集中说明当前仓库可直接运行的测试入口、后续测试分层、目录规划、OpenAPI 契约测试口径和评测门禁。它不是新的架构来源，只把 [Development Readiness](development-readiness.md)、[Automated Blind Testing Design](superpowers/specs/2026-06-14-automated-blind-testing-design.md)、[OpenAPI Contract](openapi.yaml) 和 [Deployment](deployment.md) 中的测试要求收敛成执行说明。

## 1. 当前可运行测试

当前仓库已有最小 live eval CLI 和对应 unittest。可直接运行：

```bash
python -m unittest tests.evals.test_live_cli -v
python -m evals.cli --help
```

第一条命令会启动本地临时 HTTP server，验证 quick live suite 能调用 `/health` 和 `POST /v1/reply-decisions`，并确认 `AGENT_API_TOKEN` 会作为 Bearer token 发送但不会出现在 stdout、stderr 或 Authorization 明文输出中。预期结果是 3 个 unittest 全部 `ok`，最后输出 `OK`。

第二条命令用于确认 `evals.cli` 命令行入口可用。预期结果是输出 `python -m evals.cli` 的 usage，并能看到 `run-suite` 子命令。

当前不要默认假设 `pytest` 已安装。如果本地或 CI 尚未引入 `pyproject.toml` / `requirements*.txt` 中的 pytest 依赖，先使用上面的 `unittest` 和 `python -m evals.cli --help`。等测试依赖被正式纳入项目后，再把 PR 和本地快测迁移到：

```bash
pytest tests/unit tests/contract tests/policy
pytest tests/unit tests/contract tests/integration --maxfail=1
```

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
| `/v1/system-admin/message-traces`、`/v1/system-admin/audit-logs`、`/v1/system-admin/health` | 系统排障、审计和健康检查。 |
| Customer / System Admin Web split | `admin.ecommerce-cs-agent-dev.fcihome.com` 不展示系统后台入口；`system-admin.ecommerce-cs-agent-dev.fcihome.com` 使用系统后台专用登录页、Cookie 和路由守卫。 |

后续新增、重命名或删除 OpenAPI path 时，必须同步更新 contract test 的必需路径清单。

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

Admin Web 引入前端测试后，必须补充：

```bash
npm --prefix admin-web test
npm --prefix admin-web run build
```

其中 route guard / E2E 用例至少覆盖：客户后台不出现系统后台入口；客户 Admin session 访问系统后台返回未登录或无权限；系统 Admin session 不能伪装客户用户调用客户 Admin API。

引入 pytest 后：

```bash
pytest tests/unit tests/contract tests/integration tests/policy --maxfail=1
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

引入 pytest 和 OpenAPI contract test 后，预期命令为：

```bash
pytest tests/contract --maxfail=1
```

预期：

- `docs/openapi.yaml` 可解析。
- 所有本地 `$ref` 可解析。
- 第一版必需 paths 全部存在。
- schema 必需字段、认证边界和错误结构断言全部通过。
