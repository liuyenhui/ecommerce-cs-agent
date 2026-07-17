# SACS 多 LLM 与 LangGraph 节点绑定设计

日期：2026-07-17

状态：已确认的目标设计，等待单独开发任务实施

## 1. 背景

当前 SACS 的“LLM 治理”把 Provider、Kubernetes Secret 引用、组织级路由、运行参数、草稿、版本、发布和回滚同时暴露给管理员。该设计对“配置几个模型，并指定某个 LangGraph 节点用哪个模型”这一核心需求过于复杂，而且页面概念与实际 LangGraph 节点没有直接对应关系。

本设计把 SACS 的用户模型简化为两件事：

1. 添加和维护多个可用 LLM。
2. 为每个需要 LLM 的 LangGraph 节点选择一个 LLM。

`SACS` 指 System Admin：`https://system-admin.ecommerce-cs-agent-dev.fcihome.com`。

## 2. 目标与非目标

### 2.1 目标

- 管理员可以在 SACS 中直接输入 API Key 添加多个 LLM。
- 管理员能看到真实 LangGraph 节点，并直观选择每个 LLM 节点使用哪个模型。
- 配置为全系统配置，不按租户或店铺拆分。
- 保存节点绑定后立即生效，不需要理解草稿、版本或发布流程。
- API Key 不以明文出现在数据库、日志、审计或查询响应中。
- API 服务保持 Kubernetes 无状态部署；持续状态保存在 PostgreSQL 和 Kubernetes Secret 中。

### 2.2 第一版非目标

- 不提供主模型与降级模型双路由。
- 不让用户配置温度、超时、重试、熔断或恢复探测；这些使用服务端安全默认值。
- 不提供组织级、租户级或店铺级模型覆盖。
- 不在主页面提供草稿、配置版本、发布、回滚、成本报表或高级 Provider 治理。
- 不在页面展示 Kubernetes Secret 的 namespace/name/key。

审计与变更历史仍由后端自动记录，但不是管理员完成配置所必须理解的步骤。

## 3. 页面设计

SACS 保留一个一级菜单“LLM 配置”，页面使用上下两个区块，不再使用四个治理页签。

### 3.1 可用 LLM

列表字段：

| 字段 | 说明 |
| --- | --- |
| 名称 | 管理员自定义名称，例如“客服 GPT-4.1”。 |
| 厂商 | OpenAI、DeepSeek、通义千问或“OpenAI 兼容”。 |
| 模型 | 真实模型 ID。 |
| Base URL | 厂商预设自动带出；OpenAI 兼容模式允许编辑。 |
| API Key | 创建或换 Key 时输入；列表只显示掩码和末四位。 |
| 状态 | 可用、连接失败、已停用。 |
| 最近测试 | 最近一次测试时间和安全错误摘要。 |

主要操作：新增 LLM、测试连接、编辑、换 Key、停用。只有未被必需节点使用的 LLM 才能停用；删除不是第一版必需能力。

新增表单只包含：名称、厂商、Base URL、模型 ID、API Key。保存前必须完成一次真实连接测试；测试请求使用最小 Token，设置服务端绝对超时，不回显上游正文或请求头。

### 3.2 LangGraph 节点使用的 LLM

页面展示真实节点顺序：

| 节点 | 是否使用 LLM | 第一版操作 |
| --- | --- | --- |
| `normalize_request` 归一化请求 | 否 | 显示“不使用 LLM”，不可选择。 |
| `retrieve_context` 检索上下文 | 否 | 显示“不使用 LLM”，不可选择。 |
| `classify_service_stage` 咨询阶段分类 | 是 | 选择一个已通过连接测试且启用的 LLM。 |
| `classify_intent` 识别意图 | 否 | 显示“不使用 LLM”，不可选择。 |
| `context_gate` 上下文闸门 | 否 | 显示“不使用 LLM”，不可选择。 |
| `action_gate` 动作闸门 | 否 | 显示“不使用 LLM”，不可选择。 |
| `generate_candidate` 生成候选 | 是 | 选择一个已通过连接测试且启用的 LLM。 |
| `policy_gate` 规则闸门 | 否 | 显示“不使用 LLM”，不可选择。 |
| `persist_trace` 记录检查点 | 否 | 显示“不使用 LLM”，不可选择。 |

LLM 节点由服务端注册表声明稳定 `node_id`、中文名称、是否必需和用途说明。页面不能维护一份独立硬编码节点清单。未来新增 LLM 节点时，先登记到注册表，再由同一接口自动显示。

每个 LLM 节点第一版只能绑定一个 LLM。必需节点不允许保存为空；不做无提示的自动降级。

“保存配置”一次提交全部节点绑定。服务端在单个事务中校验并替换完整绑定集合；成功响应后立即成为运行配置。若任何节点、LLM 状态或 revision 不合法，则全部失败，不允许部分更新。

## 4. API Key 安全设计

API Key 可以在 SACS 输入，但只在创建或换 Key 请求中出现一次：

1. 浏览器通过 HTTPS 把 Key 发送给 System Admin API。
2. API 使用独立 Kubernetes Secret 注入的主加密密钥 `LLM_CREDENTIAL_ENCRYPTION_KEY` 加密。
3. PostgreSQL 只保存密文、随机 nonce、加密算法版本和用于展示的末四位，不保存明文。
4. 查询接口只返回 `has_api_key` 和 `api_key_masked`，不提供解密或导出接口。
5. 运行节点需要调用模型时，服务端在内存中短暂解密；不得写入日志、trace、异常正文或审计 diff。

第一版使用带认证加密，例如 AES-256-GCM；每次写入使用独立随机 nonce。主加密密钥与模型 API Key 分离，所有 API replica 使用同一主密钥。主密钥轮换通过显式迁移任务重新加密，不允许直接替换后导致已有密文不可读。

前端密码输入框默认隐藏内容，禁止浏览器将 Key 写入 localStorage/sessionStorage、URL、埋点或错误报告。连接测试的错误只返回稳定安全错误码和脱敏说明。

## 5. 数据与接口

### 5.1 目标数据模型

- `llm_model_config`：名称、厂商、Base URL、模型 ID、密文、nonce、加密版本、末四位、启用状态、连接状态、revision 和审计时间。
- `langgraph_node_llm_binding`：稳定 `node_id` 到 `llm_model_config_id` 的全局一对一绑定、revision 和更新时间。
- `llm_connection_test`：保留操作者、目标 LLM、状态、耗时、安全错误码和时间，不保存请求/响应正文或 Key。
- `system_admin_audit_log`：自动记录新增、编辑、换 Key、测试、停用和绑定变化；换 Key 只记录“凭据已更新”。

现有 `llm_provider_config`、配置版本和场景路由属于旧治理实现。迁移阶段保留旧表供回滚和历史查询，新运行路径切换到新表并验证稳定后，再通过后续 migration 清理，不在同一次发布中直接破坏历史数据。

### 5.2 目标接口

| 接口 | 用途 |
| --- | --- |
| `GET /v1/system-admin/llms` | 获取脱敏 LLM 列表。 |
| `POST /v1/system-admin/llms` | 创建 LLM；请求可包含一次性 API Key。 |
| `PATCH /v1/system-admin/llms/{llm_id}` | 修改名称、Base URL、模型、启用状态或换 Key，使用 revision 防覆盖。 |
| `POST /v1/system-admin/llms/{llm_id}/connection-tests` | 执行真实、安全、有界的连接测试。 |
| `GET /v1/system-admin/langgraph-llm-bindings` | 返回节点注册表及当前全局绑定。 |
| `PUT /v1/system-admin/langgraph-llm-bindings` | 原子替换完整绑定集合并立即生效。 |

所有接口只接受 System Admin session。`super_admin` 和 `release_admin` 可增改 LLM 与保存绑定；`technical_support` 可读取和执行连接测试；`security_auditor` 只读。

## 6. 运行时行为

每次执行 LLM 节点时：

1. 以稳定 `node_id` 读取全局绑定。
2. 读取已启用且最近连接测试通过的 LLM 配置。
3. 在进程内短暂解密 API Key。
4. 使用该 LLM 的 Base URL、模型 ID 和服务端安全默认参数发起调用。
5. trace 记录 `node_id`、LLM ID、模型 ID、状态、耗时和安全错误码，不记录 Key、完整请求或完整模型响应。

绑定在数据库事务提交后立即对新调用生效。第一版可以每次节点调用读取数据库，或使用带 revision 主动失效的短缓存；不得依赖重启 Pod 才生效。

如果必需绑定不存在、LLM 被停用、解密失败或模型调用失败，节点进入现有失败/安全处理路径并记录明确错误，不静默切换到另一个模型。页面应把失效绑定显示为阻断状态。

## 7. 迁移与上线

为了避免切换时中断服务：

1. 新增数据库表、API、主加密密钥 Secret 和节点注册表，但先不切换运行路径。
2. 一次性迁移任务读取当前 K3s 运行配置，在内存中把现有 API Key 加密写入首个 LLM；日志只输出资源 ID 和结果。
3. 将当前 `classify_service_stage` 与 `generate_candidate` 绑定到该 LLM。
4. 验证 SACS 脱敏展示、连接测试、节点绑定和真实 Dev 决策调用。
5. 通过 feature flag 切换运行时解析器；旧环境变量保留一个可回滚发布周期。
6. 线上验证稳定后停止向业务 Pod 直接注入 `LLM_API_KEY`，后续再清理旧治理表和界面。

迁移任务必须幂等：重复执行不得生成多个默认 LLM、覆盖已人工换新的 Key 或改变已确认的节点绑定。

## 8. 验收标准

- SACS 页面只有“可用 LLM”和“LangGraph 节点使用的 LLM”两个主要区块。
- 管理员可输入 API Key 新增至少两个 LLM；刷新后只能看到掩码。
- 未通过连接测试的 LLM 不能绑定到节点。
- `classify_service_stage` 和 `generate_candidate` 可分别选择不同 LLM，并在真实 trace 中看到正确的脱敏 LLM/模型标识。
- 非 LLM 节点显示“不使用 LLM”且不可选择。
- 必需节点为空、停用被绑定 LLM 或 stale revision 时，保存完整失败且不产生部分更新。
- 保存绑定后无需发布版本或重启 Pod，新请求立即使用新配置。
- 模型失败时不静默降级，并进入既有安全失败路径。
- API、数据库、日志、审计、浏览器存储和错误报告中均不出现 API Key 明文。
- 迁移后 Dev 真实决策路径可用，旧配置仍可在约定回滚窗口恢复。

## 9. 文档同步边界

本文件记录已确认的目标设计，不声称当前代码已经实现。实施时必须同步更新 `docs/system-admin-design.md`、`docs/openapi.yaml`、部署/Runbook、安全测试和 `docs/development-handoff.md`，并删除或明确迁移旧“Provider + 场景路由 + 草稿发布”用户界面，避免新旧口径并存。
