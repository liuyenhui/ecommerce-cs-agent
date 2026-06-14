# Technical Options

本文件沉淀客服 Agent 数据存储与决策编码的技术方案对比。

## 数据存储方案

建议不要在数据库和文本之间二选一，而是采用：

> 结构化数据库做主存储 + 向量检索做知识召回 + 文件或对象存储做原始归档。

### 方案对比

| 方案 | 适合存储 | 优点 | 缺点 | 成熟度 |
| --- | --- | --- | --- | --- |
| 纯文本 / JSONL | 原始聊天归档、训练样本导出 | 简单、便宜、适合离线训练 | 查询、去重、权限、版本管理弱 | 格式成熟，生产系统不够 |
| PostgreSQL / MySQL | 会话、消息、人工回复、Agent 候选、订单快照、反馈标签 | 事务强、查询方便、权限和备份成熟 | 语义搜索弱，需要扩展 | 很成熟 |
| PostgreSQL + JSONB + pgvector | 结构化数据、半结构化上下文、向量检索 | 一个库解决大部分早期需求；JSONB 可索引；pgvector 支持向量相似搜索 | 超大规模向量检索不如专门向量库 | 推荐起步方案，成熟度高 |
| PostgreSQL + Qdrant / Milvus | 结构化主库 + 专门向量库 | 语义搜索能力强，适合知识库和相似问答召回 | 多一套系统，数据同步和运维复杂 | 中后期推荐 |
| ClickHouse / 数据仓库 | 指标分析、采用率、自动回复率、人工修改率 | 分析性能强，适合大量事件日志 | 不适合作为业务主库 | 数据量大后再加 |

### 推荐起步方案

第一阶段建议：

```text
PostgreSQL
+ JSONB
+ pgvector
+ JSONL 原始归档
```

原因：

- 对现有业务系统最友好。
- 便于存会话、消息、店铺、平台、订单快照等结构化数据。
- JSONB 能容纳不同电商平台的差异字段。
- pgvector 能支持相似问答和知识片段召回。
- 运维复杂度低于同时引入独立向量库和搜索库。

### 建议核心表

```text
conversation
message
agent_suggestion
human_reply
human_edit_diff
decision_record
knowledge_entry
feedback_label
product_snapshot
order_snapshot
```

其中最关键的是 `decision_record`，用于记录：

- 当时命中的知识。
- 风险标记。
- 置信度。
- 订单数据是否可用。
- 为什么自动回复。
- 为什么只给候选。
- 为什么转人工。

## 决策编码方案

不要让大模型自己决定是否自动回复。推荐：

> 规则闸门 + 检索评分 + 模型判断 + 历史反馈评分。

### 决策流

```text
收到消息
-> 识别意图
-> 判断风险
-> 检索商品/规则/历史人工回复
-> 生成候选回复
-> 计算置信度
-> 规则闸门判断
-> 自动回复 / 给人工候选 / 转人工
```

### 规则示例

```text
如果涉及投诉、赔付、退款争议、承诺、辱骂、平台处罚风险 -> 转人工
如果需要订单数据但拿不到 -> 转人工或请求补充信息
如果知识命中高 + 风险低 + 历史采用率高 -> 自动回复
如果知识命中中等 -> 给人工候选
如果知识命中低或模型不确定 -> 转人工
```

### 技术方案对比

| 方案 | 优点 | 缺点 | 成熟度 | 判断 |
| --- | --- | --- | --- | --- |
| 代码写死规则 | 最简单、最可控、最好调试 | 规则多了会乱 | 最高 | 第一版推荐 |
| JSON 规则引擎 | 规则可配置，可后台编辑 | 表达复杂逻辑会别扭 | 中等 | 适合运营配置低风险规则 |
| OPA / Rego | 策略即代码，审计和测试能力强 | 学习成本高，不适合生成回复本身 | 高 | 适合“是否允许自动回复”的安全闸门 |
| Drools / DMN | 企业级规则系统，很成熟 | Java 体系重，接入成本高 | 高 | 除非规则极复杂，否则不建议一开始用 |
| LangGraph | 适合多步骤 Agent、人审、状态流 | 新一些，依赖栈更复杂 | 中高 | Agent 流程复杂后可用 |
| LlamaIndex / Haystack | RAG、知识库、检索增强成熟 | 不负责业务风险决策 | 中高 | 适合知识召回，不适合当最终决策器 |
| Rasa | 对传统意图识别、对话管理成熟 | 电商客服里商品、订单、RAG、LLM 结合会比较重 | 高 | 如果要做传统机器人可选，不是首选 |

### 推荐组合

第一版：

```text
PostgreSQL + JSONB + pgvector
+ 代码规则闸门
+ RAG 检索
+ LLM 生成候选回复
+ 人工反馈闭环
```

第二阶段：

```text
Qdrant / Milvus：更强向量检索
ClickHouse：指标分析
OPA：策略治理
LangGraph：复杂 Agent 编排
```

## 置信度设计

置信度不能只用模型自评。建议综合：

- 知识命中分。
- 意图识别分。
- 规则风险等级。
- 历史人工采用率。
- 人工修改幅度。
- 用户是否继续追问。
- 是否涉及订单、退款、投诉。

这样才能让 Agent 的自动回复边界越来越稳。

## 参考资料

- PostgreSQL JSONB: https://www.postgresql.org/docs/current/datatype-json.html
- pgvector: https://github.com/pgvector/pgvector
- Qdrant: https://qdrant.tech/documentation/overview/
- Milvus: https://milvus.io/docs/overview.md
- Open Policy Agent: https://www.openpolicyagent.org/docs/latest
- LangGraph: https://docs.langchain.com/langgraph
- Haystack: https://docs.haystack.deepset.ai/docs/intro
- LlamaIndex Workflows: https://docs.llamaindex.ai/en/stable/module_guides/workflow/

