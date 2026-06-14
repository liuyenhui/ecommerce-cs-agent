# 应用技术架构

本文面向实施、客户沟通和交付说明，集中说明电商客服 Agent 使用的技术架构、数据库、编程语言、协议、AI/RAG 方案、前后台边界和接入方式。

相关详细文档：

- [System Architecture](system-architecture.md)：系统组件、数据流、数据模型和决策机制。
- [HTTP API Design](http-api-design.md)：外部系统接入 API、请求/响应、动作请求和消息追踪接口。
- [Technical Options](technical-options.md)：存储、规则引擎、RAG 和后续演进技术选型对比。
- [System Architecture HTML](system-architecture.html)：交互式架构图和数据模型视图。

## 1. 系统定位与边界

客服 Agent 是独立部署的客服决策服务，不直接嵌入现有客服系统，也不直接登录电商平台后台。

| 边界 | 说明 |
| --- | --- |
| 外部客服系统 | 负责平台消息接收、客服工作台、真正发送回复、执行真实平台 API。 |
| Agent 服务 | 负责理解消息、构建上下文、检索知识、生成候选、判断风险、输出决策。 |
| 电商平台 | 拼多多、淘宝、京东、抖音等平台仍由外部客服系统对接。 |
| LLM Provider | 提供回复生成、辅助分类、辅助抽参能力，由 Provider Adapter 屏蔽供应商差异。 |

Agent 输出的是 `auto_reply`、`candidate`、`handoff`、`context_request`、`action_request` 等结构化结果。客服问答只有一个主入口；商品、订单、物流、规则和动作执行结果按缺口单独回填。真实发送消息和真实修改订单、备注、地址等动作，仍由外部客服系统执行。

## 2. 前台 / 后台 / Agent 服务分层

| 层 | 主要职责 | 第一版形态 |
| --- | --- | --- |
| 客服前台 | 展示买家消息、Agent 候选、风险原因、追踪结果 | 外部客服系统已有工作台承载 |
| 运营后台 | 上传商品说明书、照片、视频，维护商品/SKU 资料，审核 Markdown 知识片段，配置规则和动作能力 | 可由外部后台或后续 Admin 模块承载 |
| Agent API 服务 | 提供回复决策、反馈、消息追踪、动作请求等 API | 独立 FastAPI 服务 |
| Agent 领域服务 | 上下文构建、意图识别、风险识别、RAG、生成、评分、规则闸门 | Python 服务内部模块 |
| 数据与知识层 | 保存商品资料、价格快照、会话、消息、快照、决策、候选、反馈、知识、向量 | PostgreSQL + JSONB + pgvector |

第一版建议先以“客服副驾”方式接入：外部客服系统调用 Agent，Agent 给候选和是否允许自动回复的决策；人工确认和真实发送仍在外部系统内完成。

## 3. 编程语言与服务框架

| 类别 | 推荐技术 | 说明 |
| --- | --- | --- |
| 后端语言 | Python 3.12 | Agent、RAG、模型调用和数据处理生态更直接。 |
| HTTP 框架 | FastAPI | 提供 `/v1` HTTP API，天然支持 OpenAPI 文档。 |
| Schema 校验 | Pydantic v2 | 校验请求、响应、上下文对象、模型结构化输出。 |
| ORM / 迁移 | SQLAlchemy + Alembic | 管理 PostgreSQL schema 演进。 |
| 服务运行 | Uvicorn / Gunicorn | 容器化部署简单，适合 k8s。 |
| 后续异步 | Redis + Celery 或 Dramatiq | 第一版不强依赖，消息量和耗时上来后再引入。 |

如果团队主力是 TypeScript，可用 NestJS 替换 API 层，但领域边界、数据模型、协议和决策机制保持不变。

## 4. 数据库与存储架构

第一版采用：

```text
PostgreSQL 16+
+ JSONB
+ pgvector
+ JSONL / 对象存储归档
```

| 存储 | 用途 |
| --- | --- |
| PostgreSQL | 商品资料、价格快照、会话、消息、商品快照、订单快照、决策记录、候选回复、人工反馈、规则配置。 |
| JSONB | 保存平台差异字段、原始 payload、trace、规则条件、动作 payload、扩展 metadata。 |
| pgvector | 保存审核通过知识的 embedding，支持相似问答和知识片段召回。 |
| JSONL / 对象存储 | 商品原始资料归档、训练样本导出、离线评估数据。 |

数据库详细表结构以 [System Architecture](system-architecture.md#31-核心数据库结构) 和交互式架构图的“数据模型”视图为准。本文只按职责分组：

| 分组 | 代表表 | 职责 |
| --- | --- | --- |
| 租户与平台 | `organization`、`store`、`platform_account` | 组织、店铺、平台账号和权限边界。 |
| 商品资料中心 | `product_profile`、`product_sku_profile`、`product_asset`、`product_asset_markdown`、`product_price_snapshot` | 客户手工维护商品、SKU、说明书、照片、Markdown 审稿稿件和外部价格快照。 |
| 会话与消息 | `conversation`、`message` | 外部会话、消息原文、平台消息 ID 和 raw payload。 |
| 上下文快照 | `product_snapshot`、`order_snapshot` | 保存请求当时的商品、订单、物流状态，保证决策可回放。 |
| 决策与候选 | `decision_record`、`agent_suggestion` | 保存 action、confidence、risk、trace、候选回复和模型输出。 |
| 外部动作 | `action_capability`、`action_request`、`action_result` | 把自然语言意图转成稳定动作协议，并记录执行结果。 |
| 人工反馈 | `human_reply`、`feedback_label` | 保存人工最终回复、采用/修改情况和评估标签。 |
| 知识沉淀 | `knowledge_candidate`、`product_knowledge_candidate`、`knowledge_review`、`knowledge_entry`、`knowledge_embedding`、`knowledge_eval_case` | 人工回复和商品资料先变成片段候选，经审核后入知识库并向量化；模拟问答用于覆盖率和回归评测。 |
| 规则配置 | `rule_set` | 店铺/平台规则、风险条件、动作边界和生效版本。 |

## 5. 协议与接入方式

第一版采用 HTTP/JSON 接入，同步优先，异步预留。

| 接口 / 协议 | 用途 |
| --- | --- |
| `POST /v1/reply-decisions` | 外部客服系统提交买家消息、最小会话和可选已有上下文，Agent 返回候选、自动回复决策、补上下文请求、动作请求或转人工。 |
| `POST /v1/reply-decisions/{decision_id}/contexts/products` | 按 `context_requests[type=products]` 回填商品快照或商品引用。 |
| `POST /v1/reply-decisions/{decision_id}/contexts/orders` | 按 `context_requests[type=orders]` 回填订单快照。 |
| `POST /v1/reply-decisions/{decision_id}/contexts/logistics` | 按 `context_requests[type=logistics]` 回填物流、仓库或发货状态。 |
| `POST /v1/reply-decisions/{decision_id}/contexts/rules` | 按 `context_requests[type=rules]` 回填店铺规则、平台规则或风控策略。 |
| `POST /v1/reply-decisions/{decision_id}/actions/results` | 外部系统执行真实动作后回传成功、失败、超时或错误详情。 |
| `POST /v1/feedback/human-replies` | 外部客服系统回传人工最终回复、是否采用候选、处理结果。 |
| `GET /v1/message-traces/{decision_id}` | 查询单条消息从接收到决策、反馈、知识沉淀的完整处理过程。 |
| `POST /v1/events/messages` | 后续异步事件入口，适合消息量大或决策耗时不可控时使用。 |
| `GET /v1/tasks/{task_id}` | 后续轮询查询异步任务状态。 |
| Webhook 回调 | 后续异步决策完成、动作执行结果、失败重试通知。 |

鉴权建议使用 API Key 或 Bearer Token。主请求必须带 `request_id`；补上下文和动作结果必须带 `context_request_id` / `action_id` 与 `idempotency_key`，避免外部系统重试导致重复决策、重复回填或重复动作。

## 6. AI 架构与模型访问

AI 能力通过 Provider Adapter 统一封装，业务代码不直接绑定某一个模型供应商。

```text
业务服务
-> Provider Adapter
-> OpenAI-compatible / 私有模型 / 其他模型供应商
-> 结构化输出
-> Pydantic 校验
-> 决策链路
```

| 模块 | AI 使用方式 |
| --- | --- |
| Intent Classifier | 规则优先，LLM 辅助识别商品、物流、售后、投诉、外部动作意图。 |
| Risk Detector | 关键词和规则优先，LLM 辅助识别赔付承诺、投诉升级、平台处罚风险。 |
| Reply Generator | LLM 生成候选回复，但不决定是否自动发送。 |
| Action Planner | LLM 可辅助从自然语言中抽取动作参数，但必须落到稳定 `action_type` 和结构化 `payload`。 |
| Product QA Simulation | LLM 可根据已转换 Markdown 和候选片段生成模拟买家问题、参考答案、同义问法、覆盖率提示和客服口吻改写。 |
| Confidence Scorer | 使用可解释评分函数，不直接信任模型自评分。 |
| Policy Gate | 规则闸门最终决定 `auto_reply`、`candidate` 或 `handoff`。 |

关键原则：大模型可以生成和辅助分类，也可以辅助商品资料审核前的模拟问答和覆盖率检查，但不能直接绕过规则闸门、不能最终批准知识入库，也不能直接代表系统执行外部动作。

## 7. RAG 与知识库架构

RAG 只面向审核通过的可复用知识，不把所有聊天记录直接向量化。

```text
人工回复 / 处理结果
-> feedback_label 质量信号
-> knowledge_candidate 待审核
-> Admin 审核、脱敏、改写
-> knowledge_entry
-> knowledge_embedding(pgvector)
-> Retrieval Service 召回
-> Reply Generator 生成候选
```

商品资料走独立资料审核流：

```text
客户上传说明书 / 照片 / 视频
-> product_asset 原始归档
-> product_asset_markdown 审稿稿件
-> product_knowledge_candidate 知识片段候选
-> LLM 生成模拟问答 / 覆盖率提示
-> 人工按片段对照审核
-> knowledge_entry
-> knowledge_embedding(pgvector)
-> knowledge_eval_case 回归评测样本
```

| 阶段 | 说明 |
| --- | --- |
| 候选生成 | 从人工回复、采用率、低修改幅度、低风险场景中筛出 `knowledge_candidate`。 |
| 人工审核 | Admin 审核是否可复用，必要时脱敏、改写、加标签和适用范围。 |
| 入库 | 审核通过后写入 `knowledge_entry`。 |
| 向量化 | 对 approved knowledge 生成 `knowledge_embedding`。 |
| 召回 | 按店铺、平台、商品、规则范围过滤，再做向量相似搜索。 |

这种设计避免把临时聊天、隐私信息、错误回复、未经审核的人工话术或未校对的说明书 OCR 结果直接变成自动回复知识。Markdown 是人工对照审稿格式，不直接作为自动回复知识源。

## 8. 决策规则与安全闸门

自动回复不能只看模型生成结果。第一版建议采用：

```text
规则闸门
+ 检索评分
+ 模型辅助信号
+ 历史反馈评分
+ 上下文完整度
```

| 场景 | 默认处理 |
| --- | --- |
| 商品参数、发货时间等低风险问题 | 知识命中高、上下文完整、规则允许时可 `auto_reply`。 |
| 价格类问题 | 只使用外部平台或 ERP 当前有效 `product_price_snapshot`；价格缺失、过期或冲突时不自动报价。 |
| 知识命中中等或新商品新规则 | 返回 `candidate`，由人工确认。 |
| 投诉、赔付、退款争议、平台处罚、辱骂威胁 | 强制 `handoff`。 |
| 需要商品/订单/物流/规则但上下文缺失 | 一次性返回 `context_requests[]`；客户端按类型并行回填。5 秒内仍缺关键上下文时返回 `candidate` 或 `handoff`，禁止猜测。 |
| 外部动作执行未成功 | 不允许回复“已完成”，只能等待结果、给候选或转人工。 |

外部动作必须通过 `action_request` 和 `action_result` 闭环：Agent 只规划动作，外部系统执行真实 API，成功回调后 Agent 才能生成完成确认。

## 9. 消息追踪、审计与观测

每次决策都必须生成 `decision_id`，并写入 `decision_record.trace`。

追踪信息应覆盖：

- 请求输入摘要和上下文快照引用。
- 选中的商品、商品资料版本、SKU、价格快照、订单、规则和会话摘要。
- 知识召回结果、相似度、来源。
- 商品资料 Markdown 来源、知识片段审核状态和模拟问答引用。
- 模型版本、Prompt 版本、结构化输出摘要。
- 风险标记、规则命中、置信度和最终 action。
- 外部动作请求、执行结果、失败或降级原因。
- 人工反馈、采用/修改情况、后续知识候选。

观测建议：

| 类型 | 指标 |
| --- | --- |
| 技术指标 | API 延迟、模型耗时、数据库耗时、错误率、重试次数。 |
| 业务指标 | 候选采用率、自动回复率、转人工原因、追问率、人工修改幅度。 |
| 安全指标 | 高风险拦截次数、P0/P1 规则命中、外部动作失败率。 |

## 10. 部署架构与 k8s 无状态原则

Agent 服务按无状态容器部署，适合 k8s 横向扩缩容。

| 部署对象 | 建议 |
| --- | --- |
| Agent API | Docker 容器，k8s Deployment，多副本无状态。 |
| PostgreSQL | 独立有状态服务，使用 PVC 或云数据库，安装 `pgcrypto` 和 `vector` 扩展。 |
| 对象存储 | MinIO 或云对象存储，用于 JSONL 归档和导出。 |
| Redis / Queue | 后续异步任务再引入。 |
| Ingress | HTTPS 入口，配合证书管理和访问控制。 |
| Secret | API Key、模型密钥、数据库密码使用 Secret 管理。 |

无状态原则：

- API 容器不保存本地业务状态。
- 所有商品资料元数据、价格快照、会话、决策、反馈、规则、知识写入 PostgreSQL。
- 商品原始文件、原始归档和训练导出写入对象存储。
- 幂等依赖数据库唯一约束和外部 `request_id`，不依赖单实例内存。

## 11. 第一版与后续演进边界

第一版聚焦可控闭环：

- 外部系统同步提交最小问答请求，商品、订单、物流、规则作为可选上下文或按 `context_requests[]` 并行回填。
- 客户后台手工维护商品资料，说明书先转 Markdown 并按知识片段审核。
- Agent 返回候选回复、自动回复决策、转人工原因。
- 动作类需求先补必要订单或物流上下文，再返回 `action_request`；外部系统执行后调用 `actions/results`。
- 单次问答等待预算最高 5 秒，超时降级为候选或人工介入。
- 规则闸门控制自动回复边界。
- 人工反馈回流，形成评估和知识候选。
- PostgreSQL + JSONB + pgvector 支撑业务数据和 RAG。
- 外部平台或 ERP 价格快照作为价格类回答权威来源。
- 消息追踪可解释每次决策。

后续再逐步加入：

- 异步事件、任务队列、Webhook 回调。
- Connector 主动查询外部商品、订单、规则。
- 更完整的 Admin 配置后台。
- 规则灰度、策略治理、OPA/Rego。
- 独立向量库、ClickHouse 指标分析。
- LangGraph / LlamaIndex / Haystack 等更复杂 Agent 编排。

这条路径优先保证第一版能低风险上线，再逐步提高自动化比例。
