# 数据库迁移实施口径

本文定义 `ecommerce-cs-agent` 数据库迁移的命名、执行、验收和安全口径。它是实施说明，不替代 [System Architecture](system-architecture.md) 的数据模型；表结构、字段语义和业务边界仍以系统架构、应用技术架构和接口契约为准。

相关来源：

- [System Architecture](system-architecture.md)：核心数据模型、决策记录、检查点、知识和反馈表的业务语义。
- [Application Technology Architecture](application-technology-architecture.md)：PostgreSQL、JSONB、pgvector、SQLAlchemy / Alembic 和 k8s 无状态部署原则。
- [Deployment](deployment.md)：当前 dev PostgreSQL、扩展、Secret 和部署状态。
- [Development Readiness](development-readiness.md)：第一版实现范围、验收命令和安全边界。

## 1. 当前 dev PostgreSQL 状态

当前 dev 环境状态来自 [Deployment](deployment.md)：

| 项目 | 当前值 |
| --- | --- |
| PostgreSQL | `16.14` |
| Database | `cs_agent` |
| Extensions | `pgcrypto`、`vector` 已启用 |
| Migration | dev 执行状态以 `schema_migration` 为准；应用仓库当前声明 `001_initial.sql` 到 `006_system_admin_ops.sql` |

dev 环境已经具备第一版迁移的基础能力。后续不得直接手工改线上表结构；所有 schema 演进都必须通过可追踪的 migration 文件进入。

## 2. Migration 命名

迁移文件使用三位递增序号加短描述：

```text
NNN_short_description.sql
```

示例：

```text
001_initial.sql
002_admin_sessions.sql
003_action_result_indexes.sql
```

命名规则：

- `NNN` 必须按执行顺序递增，不复用、不插队。
- `short_description` 使用英文小写、数字和下划线，描述本次 schema 变化，不写业务数据或环境名。
- 已经在任一共享环境执行成功的 migration 不再改写；需要修正时新增下一号 migration。
- 一个 migration 应聚焦一组可评审的结构变更，避免把无关表、索引和大规模回填混在一起。

## 3. `schema_migration` 规则

`schema_migration` 是迁移执行记录表，用于判断文件是否已经成功应用。

建议字段：

| 字段 | 规则 |
| --- | --- |
| `version` | 唯一，对应文件序号或完整文件名中的版本号，例如 `001`、`002`。 |
| `checksum` | 记录 migration 文件内容校验值，用于发现已执行文件被改写。 |
| `applied_at` | 执行成功后写入数据库时间。 |

执行规则：

- 执行前按文件名排序，逐个检查 `schema_migration.version`。
- 如果 `version` 不存在，执行 migration；全部成功后再写入 `version`、`checksum`、`applied_at`。
- 如果 `version` 已存在且 `checksum` 一致，视为已应用并跳过。
- 如果 `version` 已存在但 `checksum` 不一致，必须停止执行并人工排查，不得覆盖记录。
- 单个 migration 应尽量在事务中执行；不能放入事务的语句必须在文件和评审中明确说明。
- 重复执行必须幂等或安全失败：能使用 `IF NOT EXISTS`、唯一约束、检查条件的地方优先使用；无法幂等时必须让数据库以明确错误中止，不能产生半成功状态。

## 4. 扩展初始化

第一版依赖 `pgcrypto` 和 `pgvector`。初始化 migration 必须包含：

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
```

扩展初始化规则：

- `pgcrypto` 用于 UUID、随机值或加密相关数据库函数。
- `vector` 用于知识向量字段和相似召回索引。
- 本地、dev、prod 都应通过同一 migration 声明扩展依赖，避免依赖人工预置。
- 如果目标环境没有安装 `pgvector` 扩展包，迁移必须失败并让部署流程停止，不能降级成缺少向量字段的半成品 schema。

## 5. 第一版核心表批次

第一版 migration 应覆盖客服 Agent 闭环所需的核心表。具体字段仍以系统架构的数据模型为准，迁移文件负责把该模型落为可执行 SQL。

当前迁移批次：

| 文件 | 目的 |
| --- | --- |
| `001_initial.sql` | 初始规范表、`pgcrypto`、`vector`、租户/店铺、决策、知识、审计核心结构。 |
| `002_v1_runtime_alignment.sql` | 第一版运行时快速表和 legacy 兼容表。 |
| `003_canonical_runtime_alignment.sql` | 外部租户/店铺映射、规范决策/知识/商品表兼容列和索引。 |
| `004_admin_auth_runtime.sql` | 客户 Admin membership、invitation、session 扩展。 |
| `005_legacy_runtime_defaults.sql` | dev 旧 schema 的必需默认值和兼容列。 |
| `006_system_admin_ops.sql` | 系统后台运维任务表、任务查询/重试索引和系统审计查询索引。 |

| 批次 | 代表表 |
| --- | --- |
| 租户、店铺、平台账号 | `tenant`、`store`、`platform_account` |
| Admin 用户、会话、审计 | `admin_user`、`admin_session`、`audit_log` |
| 会话与消息 | `conversation`、`message` |
| 上下文快照 | `product_snapshot`、`order_snapshot`，以及后续需要的物流、规则或商品资料快照 |
| 决策记录 | `decision_record` |
| LangGraph 检查点 | `decision_graph_checkpoint` |
| 候选回复 | `agent_suggestion` |
| 外部动作闭环 | `action_capability`、`action_request`、`action_result` |
| 人工反馈 | `human_reply`、`feedback_label` |
| 商品资料中心 | `product_master`、`product_sku`、`listing` / `store_product`、`product_asset`、`product_asset_markdown`、`product_price_snapshot` |
| 知识沉淀与召回 | `knowledge_candidate`、`product_knowledge_candidate`、`knowledge_review`、`knowledge_entry`、`knowledge_embedding`、`knowledge_eval_case` |
| 规则配置 | `rule_set` |

核心约束：

- 业务表必须能回溯到 `tenant` 或 `store`，避免跨租户、跨店铺串数据。
- 外部幂等字段如 `request_id`、`external_message_id`、`idempotency_key` 应有唯一约束或等价保护。
- `decision_record`、`decision_graph_checkpoint`、`action_request`、`action_result` 和审计表是排障与可回放的关键路径，不能只做内存状态。
- `knowledge_embedding` 只服务审核通过知识，不能直接把未审核聊天或客户原始资料向量化。

## 6. 本地、dev、prod 执行策略

| 环境 | 策略 |
| --- | --- |
| 本地 | 可以重建数据库或清空 schema 后重新执行全部 migration；只允许使用本地假数据或脱敏样例。 |
| dev | 只做前进迁移，不改写已执行 migration；迁移后检查扩展、`schema_migration` 和关键表。 |
| prod | 执行前必须有备份、SQL 评审、影响评估、执行窗口和回滚方案；执行后必须保留验收记录。 |

dev 和 prod 都不允许通过数据库客户端临时补结构来绕过 migration。紧急修复也应落成新的 migration 文件，并在执行记录中可追踪。

## 7. 回滚与破坏性变更

回滚优先采用前进修复，而不是直接逆向执行旧 migration。

规则：

- 生产环境优先新增修复 migration，例如补索引、补字段、修约束、修数据校验。
- 破坏性变更必须拆成 `expand`、`backfill`、`contract` 三步：
  - `expand`：先新增兼容字段、表或索引，应用代码开始双写或兼容读取。
  - `backfill`：后台或脚本分批补齐历史数据，并记录批次、数量和失败项。
  - `contract`：确认代码不再读取旧结构、备份可恢复、监控无异常后，才能在后续版本收缩旧结构。
- 不得直接 drop 生产字段、生产表或生产索引，除非已经完成评审、备份、兼容窗口和回滚方案。
- 涉及大表回填、锁表、索引重建或约束收紧时，需要先在 dev 或 staging 验证耗时和锁影响。
- 数据修复 migration 只能写入必要的结构化修复逻辑，不写入真实客户数据样本。

## 8. 验收命令示例

以下命令使用占位连接变量，不包含真实连接串。实际执行时连接信息应来自本地安全配置、Kubernetes Secret、CI Secret 或外部 Secret Manager。

检查扩展：

```bash
psql "$CS_AGENT_DB_DSN" -c "SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto', 'vector') ORDER BY extname;"
```

检查迁移记录：

```bash
psql "$CS_AGENT_DB_DSN" -c "SELECT version, checksum, applied_at FROM schema_migration ORDER BY version;"
```

检查关键表存在：

```bash
psql "$CS_AGENT_DB_DSN" -c "
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'tenant',
    'store',
    'platform_account',
    'admin_user',
    'admin_session',
    'audit_log',
    'conversation',
    'message',
    'decision_record',
    'decision_graph_checkpoint',
    'agent_suggestion',
    'action_request',
    'action_result',
    'human_reply',
    'feedback_label',
    'knowledge_entry',
    'knowledge_embedding',
    'rule_set'
  )
ORDER BY table_name;"
```

检查 `001_initial.sql` 是否已记录：

```bash
psql "$CS_AGENT_DB_DSN" -c "SELECT version, applied_at FROM schema_migration WHERE version = '001';"
```

验收输出只应包含扩展名、表名、版本号、时间、行数和错误摘要，不应打印连接串、密码、token、客户消息正文或 raw payload。

## 9. 安全要求

- 不得在 SQL、日志、文档、迁移注释或错误输出中写入 Secret、API Key、数据库密码、LLM Key、JWT / session secret 或客户生产数据。
- migration 示例只能使用占位符、假数据或本地脱敏数据。
- 回填脚本不得把生产客户内容写入仓库、CI 日志或评审文档。
- 审计、trace 和 raw payload 字段可以定义结构，但文档中不粘贴真实客户样本。
- 提交前如涉及部署、CI/CD、配置或 SQL，应检查 staged diff，确认没有 Secret、私钥、真实连接串或客户数据。
