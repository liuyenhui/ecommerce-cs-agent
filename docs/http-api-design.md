# HTTP API Design

本文件定义客服 Agent 作为独立系统时，对外提供的标准 HTTP API 设计方向。

系统组件、数据流、数据模型和决策机制详见 [System Architecture](system-architecture.md)。客户可登录后台的详细设计见 [Customer Admin Design](customer-admin-design.md)。

## 系统边界

客服 Agent 应作为独立服务部署，不直接嵌入现有客服系统。外部系统通过 HTTP API 接入，把客服消息、可选上下文和人工反馈传给 Agent；当缺商品、订单、物流、规则或动作执行结果时，Agent 返回结构化补上下文请求，由外部系统按类型回填。Agent 最终返回候选回复、自动回复决策、转人工原因、动作请求和可追踪的决策记录。

外部系统是通用接入方，可以是客服系统、ERP、订单、仓储或平台自动化系统。ERP 只是其中一种实现示例，不是默认上游、统一身份源或必需组件。

第一版目标不是替代现有客服系统，而是提供一个可控的客服决策服务：

- 外部系统负责接收平台消息、展示客服界面、真正发送回复。
- 公开宣传页属于客服 Agent 自身，只展示产品能力和登录入口，不承载外部系统接入或租户业务数据。
- 客户 Admin 后台属于客服 Agent 自身，负责登录、组织/店铺切换、商品资料维护、知识审核、规则配置、动作能力配置和审计查询。
- Agent 服务负责理解消息、检索知识、生成候选、判断风险、输出决策。
- Agent 内部可用 LangGraph 编排决策状态、补上下文等待、动作结果等待和人工介入；对外仍只暴露稳定 HTTP API，不暴露 graph 节点或 LangGraph runtime。
- 自动回复必须经过规则闸门，不能只依赖模型自评。
- 所有决策都要生成 `decision_id`，便于后续追踪、反馈和评估。

## 接入形态

采用“同步优先，异步预留”的设计。

### 公开页面、客户 Admin 与系统 Admin 入口

公开页面和 Admin 路由是客服 Agent 自有 Web 入口，不属于外部系统 API。客户后台和系统后台必须拆成不同 Web 站点、登录页、Cookie / session 名和路由守卫：

```text
GET https://admin.ecommerce-cs-agent-dev.fcihome.com/
GET https://admin.ecommerce-cs-agent-dev.fcihome.com/login
GET https://admin.ecommerce-cs-agent-dev.fcihome.com/admin
GET https://system-admin.ecommerce-cs-agent-dev.fcihome.com/login
GET https://system-admin.ecommerce-cs-agent-dev.fcihome.com/
```

- `admin.ecommerce-cs-agent-dev.fcihome.com` 只承载公开宣传页、客户 Admin 登录页和客户后台 shell，不展示“系统后台”入口。
- 客户后台登录成功后建立客户 Admin session，例如 `agent_admin_session`，并跳转 `/admin`；客户后台路由守卫只调用 `GET /v1/admin/auth/me`。
- `system-admin.ecommerce-cs-agent-dev.fcihome.com` 承载系统 Admin 登录页和系统后台 shell，`ops-admin.ecommerce-cs-agent-dev.fcihome.com` 只作为可选别名。
- 系统后台登录成功后建立系统 Admin session，例如 `agent_system_admin_session`；系统后台路由守卫只调用 `GET /v1/system-admin/auth/me`。
- 客户 Admin session、系统 Admin session 和外部系统 API token 互不互认；服务端 session 状态必须保存在数据库、Redis 或等价外部存储，不能依赖单容器内存。

### 第一版：同步接口

外部系统收到买家消息后，调用同步接口获取决策：

```text
POST /v1/reply-decisions
```

适用场景：

- 人工客服界面需要立即看到 Agent 候选回复。
- 外部系统希望在低风险场景下立即判断是否允许自动回复。
- 第一阶段快速接入，不引入复杂消息队列、回调和任务状态管理。

### 后续：异步事件和回调

当消息量变大、决策耗时变长，或需要后台学习任务时，再扩展异步接口：

```text
POST /v1/events/messages
GET /v1/tasks/{task_id}
POST <external_callback_url>
```

适用场景：

- 高并发消息处理。
- 需要长时间检索、跨系统查询或多轮 Agent 流程。
- 外部系统希望先提交事件，再通过回调或轮询获取结果。

## 上下文输入

第一版采用“最小问答请求 + 可选已有上下文 + 按类型补上下文”的模式。`POST /v1/reply-decisions` 是唯一客服问答入口，只负责接收买家问题并推进决策，不要求每次都传商品、订单、物流和规则全集。

同步决策请求必填字段只保留：

- `request_id`：外部请求幂等键。
- `organization_id` / `store_id`：租户和店铺隔离字段。
- `platform`：平台标识。
- `message`：买家当前消息、平台消息 ID、发送时间。
- `conversation`：最小会话上下文，至少包含外部会话 ID、买家脱敏引用和可选最近消息。
- `mode`：决策模式，例如 `assist_first`、`auto_when_safe`。

商品、订单、物流和规则都是可选上下文。外部系统如果已经有低成本、可信的上下文，可以随主请求传入；如果没有，Agent 先做轻量意图和上下文需求判断，一次性返回当前可判断出的 `context_requests[]`。客户端按类型并行调用补充接口，服务端用同一个 `decision_id` 聚合上下文，直到返回明确可答复内容、动作请求或人工介入。

内部编排推荐使用 LangGraph：`decision_id` 映射 graph `thread_id`，主请求、typed context refill 和 `actions/results` 都恢复同一条 thread。LangGraph checkpoint 必须落 PostgreSQL、Redis 或等价外部存储；API 容器不能依赖内存保存 graph state。

实时性上下文采用“最近有效快照”规则：同一连续聊天里出现多个商品、订单、规则或会话摘要时，Context Builder 以当前消息显式引用为优先，其次按外部业务更新时间选择最近有效项。订单优先看订单状态更新时间、物流更新时间、支付时间；商品优先看商品更新时间、SKU 或活动更新时间；规则优先看 `effective_at` 或版本生效时间；缺失这些时间时使用 Agent 接收请求时的 `captured_at`。被替换的旧上下文不删除，只作为历史快照保留，用于回放和审计。

商品说明书、照片、视频和长期 SKU 资料不建议塞进 `POST /v1/reply-decisions` 请求体。第一版由客户在 Admin 后台手工维护商品资料：原始资料先进入 `product_asset` 归档，再转换为 `product_asset_markdown` 审稿稿件，抽取 `product_knowledge_candidate` 知识片段，人工审核通过后才进入知识库和向量召回。价格类回答以外部系统当前有效 `product_price_snapshot` 为权威；价格缺失、过期或冲突时，Agent 返回候选、补上下文或转人工，不能自动报价。

性能规则：

- Agent 在完整 LLM 生成前先做轻量意图和上下文需求判断，避免缺关键数据时浪费模型调用。
- 不做串行逐字段补查；`context_requests[]` 一次返回当前可判断出的全部缺口。
- 客户端并行处理多个补上下文请求；服务端聚合同一 `decision_id` 下的回填结果。
- 同一会话、订单、商品、物流短时间内可复用快照，减少重复补查。
- 推荐 SLA：普通知识问答 0.8-1.5 秒；单个上下文补充 2-4 秒；多个上下文并行补充 3-5 秒；超过 5 秒则降级为候选或人工介入。

## 核心接口建议

### 创建回复决策

```text
POST /v1/reply-decisions
```

请求重点字段：

```json
{
  "request_id": "external-idempotency-key",
  "organization_id": "org-001",
  "platform": "pdd",
  "store_id": "store-001",
  "message": {
    "external_message_id": "msg-001",
    "sender_type": "buyer",
    "content": "这个订单什么时候发货？",
    "sent_at": "2026-06-12T10:15:00+08:00"
  },
  "conversation": {
    "external_conversation_id": "conv-001",
    "buyer_ref": "buyer-hash-001",
    "messages": []
  },
  "mode": "assist_first",
  "context": {
    "products": [],
    "orders": [],
    "logistics": [],
    "rules": []
  }
}
```

返回重点字段：

```json
{
  "decision_id": "decision-001",
  "decision_status": "waiting_context",
  "action": "context_request",
  "candidates": [],
  "auto_reply": null,
  "context_requests": [
    {
      "context_request_id": "ctx-001",
      "type": "orders",
      "endpoint": "/v1/reply-decisions/decision-001/contexts/orders",
      "reason": "用户询问订单发货时间，但当前请求没有订单上下文",
      "query": {
        "buyer_ref": "buyer-hash-001",
        "store_id": "store-001",
        "conversation_id": "conv-001",
        "time_window": "recent"
      },
      "deadline_ms": 5000,
      "fallback_action": "candidate"
    },
    {
      "context_request_id": "ctx-002",
      "type": "logistics",
      "endpoint": "/v1/reply-decisions/decision-001/contexts/logistics",
      "reason": "发货时间回答需要物流或仓库状态",
      "query": {
        "order_ref": "latest_order_for_buyer",
        "store_id": "store-001"
      },
      "deadline_ms": 5000,
      "fallback_action": "handoff"
    }
  ],
  "action_requests": [],
  "confidence": 0.72,
  "risk_level": "medium",
  "risk_flags": [],
  "missing_context": ["orders", "logistics"],
  "handoff_reason": null,
  "trace": {
    "matched_knowledge_ids": [],
    "rule_hits": [],
    "graph_version": "reply-decision-graph-v1",
    "model_version": "reply-generator-v1",
    "steps": [
      {
        "step_id": "retrieval",
        "name": "知识召回",
        "status": "completed",
        "started_at": "2026-06-01T10:00:01Z",
        "ended_at": "2026-06-01T10:00:01Z",
        "inputs_ref": ["message:msg-001", "rule_set:shipping-v3", "product_price_snapshot:pps-001"],
        "outputs_ref": ["knowledge_entry:faq-123", "knowledge_eval_case:kec-001"],
        "error": null
      }
    ]
  }
}
```

`decision_status` 建议固定为：

- `received`：已接收请求，尚未完成轻量判断。
- `waiting_context`：已返回 `context_requests[]`，等待外部系统回填关键上下文。
- `partial_context`：已收到部分上下文，但仍缺关键上下文。
- `ready_to_decide`：上下文足够，准备生成或进入规则闸门。
- `answer_ready`：已形成可答复结果。
- `candidate`：给人工候选回复。
- `action_request`：需要外部系统执行结构化动作。
- `handoff`：应转人工。
- `failed`：处理失败，trace 中必须记录错误。

`action` 建议固定为：

- `auto_reply`：允许外部系统自动发送。
- `candidate`：只给人工候选回复。
- `handoff`：转人工，不建议自动回复。
- `context_request`：缺商品、订单、物流、规则或动作结果，需要外部系统回填。
- `action_request`：需要外部系统执行结构化动作。

`context_requests` 和 `action_requests` 用于把“问答”扩展成可控的外部系统协作：

- `context_requests`：Agent 缺订单、商品、物流、规则或动作结果时，一次性返回所有当前可判断出的缺口。
- `action_requests`：Agent 判断用户要执行外部动作时，请外部系统按稳定动作协议执行。

自然语言只用于 Admin 配置和意图识别，真正对接外部系统时必须落到稳定的 `action_type`、结构化 `payload` 和执行结果回调。

### 外部能力清单和动作配置

外部系统应向 Agent 暴露平台级或店铺级能力清单。Admin 可以用自然语言维护触发表达，但执行契约必须是稳定动作名：

```json
{
  "scope": "store",
  "platform": "pdd",
  "store_id": "store-001",
  "capabilities": [
    {
      "action_type": "update-note",
      "description": "修改订单备注",
      "intent_examples": ["改备注", "帮我备注", "订单备注写一下", "备注要红色"],
      "required_context": ["order_id"],
      "payload_schema": {
        "note": "string"
      },
      "risk_level": "low",
      "requires_human_confirm": true,
      "callback_url": "https://external.example.com/agent-actions"
    },
    {
      "action_type": "update-address",
      "description": "修改收货地址",
      "intent_examples": ["改地址", "收货地址换成", "帮我修改地址"],
      "required_context": ["order_id"],
      "payload_schema": {
        "recipient": "string",
        "phone": "string",
        "address": "string"
      },
      "risk_level": "high",
      "requires_human_confirm": true,
      "callback_url": "https://external.example.com/agent-actions"
    }
  ]
}
```

配置优先级建议为：店铺级能力配置 > 平台级能力配置 > 系统默认配置。外部系统只需要识别 `action_type`，再调用自己的真实平台 API。

### 按类型补上下文

当用户表达依赖商品、订单、物流或规则，但本次请求没有可靠上下文时，Agent 不应猜测，也不应把缺失当作“没有”。同步接口直接返回 `context_requests[]`；客户端按类型并行调用对应回填接口。不要设计一个大而全的统一回填接口，缺什么补什么，需要多个时并行补齐。

补上下文接口：

```text
POST /v1/reply-decisions/{decision_id}/contexts/products
POST /v1/reply-decisions/{decision_id}/contexts/orders
POST /v1/reply-decisions/{decision_id}/contexts/logistics
POST /v1/reply-decisions/{decision_id}/contexts/rules
POST /v1/reply-decisions/{decision_id}/actions/results
```

`context_requests[]` 示例：

```json
[
  {
    "context_request_id": "ctx-orders-001",
    "type": "orders",
    "endpoint": "/v1/reply-decisions/decision-001/contexts/orders",
    "reason": "用户要求修改订单备注，但当前请求未提供订单上下文",
    "query": {
      "buyer_ref": "buyer-001",
      "store_id": "store-001",
      "conversation_id": "conv-001",
      "time_window": "recent"
    },
    "required_for_action": "update-note",
    "deadline_ms": 5000,
    "fallback_action": "handoff"
  },
  {
    "context_request_id": "ctx-logistics-001",
    "type": "logistics",
    "endpoint": "/v1/reply-decisions/decision-001/contexts/logistics",
    "reason": "用户问发货进度，需要物流或仓库状态",
    "query": {
      "external_order_id": "order-123"
    },
    "deadline_ms": 5000,
    "fallback_action": "candidate"
  }
]
```

回填请求示例：

```json
{
  "context_request_id": "ctx-orders-001",
  "idempotency_key": "decision-001:ctx-orders-001:v1",
  "captured_at": "2026-06-12T10:15:02+08:00",
  "orders": [
    {
      "external_order_id": "order-123",
      "status": "paid",
      "paid_at": "2026-06-12T09:55:00+08:00",
      "items": [
        {
          "external_product_id": "product-001",
          "sku": "red-l",
          "quantity": 1
        }
      ],
      "business_updated_at": "2026-06-12T10:12:00+08:00",
      "raw_payload": {
        "source": "external_cs_order_api",
        "payload_ref": "raw:order:order-123"
      }
    }
  ]
}
```

回填响应示例：

```json
{
  "decision_id": "decision-001",
  "context_request_id": "ctx-orders-001",
  "decision_status": "partial_context",
  "accepted": true,
  "remaining_context_requests": [
    {
      "context_request_id": "ctx-logistics-001",
      "type": "logistics",
      "endpoint": "/v1/reply-decisions/decision-001/contexts/logistics"
    }
  ],
  "next_action": "wait_context"
}
```

服务端用 `decision_id + context_request_id + idempotency_key` 做幂等和聚合。若内部使用 LangGraph，回填接口应恢复同一个 graph `thread_id`，并写入 `decision_graph_checkpoint` 或等价 checkpointer。总等待预算最高 5 秒；超过预算仍缺关键上下文时，Agent 返回 `candidate` 或 `handoff`，不能继续阻塞客服界面。trace 必须记录每个补充请求、回填接口、LangGraph 节点、耗时、成功/失败、是否超时和最终是否降级。

### 动作请求和执行结果

例如用户说“帮我备注：要红色”，Agent 的流程应是：识别 `update-note` 意图，确认订单上下文，生成动作请求，等待外部系统执行结果，再生成最终回复。

```json
{
  "type": "action_request",
  "action_id": "act-001",
  "action_type": "update-note",
  "target": {
    "order_id": "order-123"
  },
  "payload": {
    "note": "要红色"
  },
  "confidence": 0.88,
  "risk_level": "low",
  "requires_human_confirm": true,
  "reason": "用户明确要求修改订单备注",
  "idempotency_key": "req-001:update-note:order-123"
}
```

外部系统执行自己的订单备注 API 后，通过 `POST /v1/reply-decisions/{decision_id}/actions/results` 把结果回传给 Agent：

```json
{
  "action_id": "act-001",
  "action_type": "update-note",
  "idempotency_key": "decision-001:act-001:result",
  "status": "succeeded",
  "external_result": {
    "order_id": "order-123",
    "note": "要红色"
  },
  "executed_at": "2026-06-02T10:30:00Z"
}
```

执行成功后，Agent 才能生成“已帮您备注‘要红色’”这类确认回复；执行失败或超时时，必须降级为 `candidate` 或 `handoff`，不能假装已完成。

### 查询单条消息 Agent 处理过程

```text
GET /v1/message-traces/{decision_id}
```

用于客服运营、技术排障和审计场景，按单条客服消息查询 Agent 从接收请求到输出决策、人工反馈和知识沉淀的完整信息流。路径参数优先使用 `decision_id`；如果外部系统只有消息或幂等键，也可以通过查询参数定位：

```text
GET /v1/message-traces/{decision_id}?message_id=msg-001&external_message_id=pdd-msg-001&request_id=req-001
```

返回重点字段：

```json
{
  "decision_id": "decision-001",
  "message_id": "msg-001",
  "external_message_id": "pdd-msg-001",
  "request_id": "req-001",
  "platform": "pdd",
  "store_id": "store-001",
  "conversation_id": "conv-001",
  "action": "candidate",
  "confidence": 0.72,
  "risk_level": "medium",
  "sections": {
    "ingest": {},
    "normalization": {},
    "retrieval": {},
    "generation": {},
    "risk_and_policy": {},
    "persistence": {},
    "feedback": {}
  },
  "trace": {
    "steps": [
      {
        "step_id": "api_check",
        "name": "鉴权 / 幂等 / Schema",
        "status": "completed",
        "started_at": "2026-06-01T10:00:00Z",
        "ended_at": "2026-06-01T10:00:00Z",
        "inputs_ref": ["request:req-001"],
        "outputs_ref": ["message:msg-001"],
        "error": null
      }
    ]
  }
}
```

`sections` 按信息流分段返回：

- `ingest`：外部客服系统传入的消息、商品、订单、规则、会话上下文摘要。
- `normalization`：字段映射、缺失上下文、raw payload 保存结果。
- `retrieval`：命中的知识、历史人工回复、规则、相似度分数。
- `generation`：模型版本、prompt 版本、候选回复、结构化模型输出。
- `risk_and_policy`：风险标记、规则命中、置信度、最终 `action`。
- `persistence`：写入的 `conversation`、`message`、`decision_record`、`agent_suggestion`。
- `feedback`：人工是否采用、修改幅度、最终回复、追问或升级结果。

`trace.steps` 用于渲染信息流转图。每个步骤必须包含 `step_id`、`name`、`status`、`started_at`、`ended_at`、`inputs_ref`、`outputs_ref` 和 `error`。默认响应只返回摘要、引用 ID、命中原因和审计元数据；完整 raw payload 只允许有内部排障权限的角色读取。

### 提交人工反馈

```text
POST /v1/feedback/human-replies
```

用于记录人工最终回复、是否采用 Agent 候选、人工修改幅度和处理结果。

关键字段：

- `decision_id`
- `human_reply`
- `used_candidate`
- `edit_distance`
- `resolution_status`
- `follow_up_required`
- `escalation_type`

这部分是后续学习闭环的核心数据，不能只存最终聊天文本。

### 知识和规则维护

```text
POST /v1/knowledge/entries
POST /v1/rules/store-rules
POST /v1/rules/platform-rules
POST /v1/capabilities/action-capabilities
```

这些接口服务第一版客户 Admin 后台，也可以支持批量导入或简单 upsert。动作能力配置用于保存平台级 / 店铺级 `action_type`、自然语言触发表达、参数 schema、风险级别和回调地址；后台负责维护版本、审计和基础规则测试，灰度发布可后续增强。

### Admin 登录、权限和审计

客户后台使用客服 Agent 自有 Admin API 分组承载登录、组织/店铺上下文、用户角色和审计查询，不扩大同步问答接口，也不依赖任何外部系统的登录态、session 或 token。客户后台站点为 `admin.ecommerce-cs-agent-dev.fcihome.com`，公开路由 `/`、`/login`、`/admin` 只负责页面入口和后台 shell，真实登录状态由以下 API 校验：

```text
POST /v1/admin/auth/login
POST /v1/admin/auth/logout
GET /v1/admin/auth/me
GET /v1/admin/organizations
GET /v1/admin/stores
PATCH /v1/admin/stores/{store_id}/settings
GET /v1/admin/users
POST /v1/admin/invitations
PATCH /v1/admin/users/{user_id}/roles
GET /v1/admin/audit-logs
```

Admin API 必须校验 Agent 自有用户身份、组织、店铺和角色权限。外部系统接入 token 和系统 Admin session 不能直接访问 `/v1/admin/*`。所有商品资料、知识审核、规则配置、动作能力配置和店铺设置的写操作都应记录操作者、组织、店铺、对象、动作和时间。未登录访问客户后台 `/admin` 必须回到客户后台 `/login`，登录成功后如果用户有多个组织或店铺，应先选择上下文再进入后台首页。系统后台如需代客户操作，必须走 `/v1/system-admin/*` 专用接口并写系统审计，不得伪装客户用户调用 `/v1/admin/*`。

### 商品资料维护

商品资料维护属于第一版 Admin/API 能力，不扩大同步决策接口。接口方向如下：

```text
POST /v1/product-content/products
POST /v1/product-content/assets
POST /v1/product-content/assets/{asset_id}/markdown
POST /v1/product-content/knowledge-candidates/{candidate_id}/reviews
POST /v1/product-content/price-snapshots
GET /v1/product-content/products/{product_id}/health
```

这些接口用于维护 `product_profile`、`product_sku_profile`、`product_asset`、`product_asset_markdown`、`product_knowledge_candidate`、`knowledge_eval_case` 和 `product_price_snapshot`。客户上传说明书、照片或视频后，系统必须保留原始文件和版本，再转换为 Markdown 审稿稿件。LLM 可以基于 Markdown 和候选片段生成模拟买家问题、参考答案、同义问法和覆盖率提示，但人工必须按知识片段对照原文审核，批准后才写入 `knowledge_entry` 并生成 `knowledge_embedding`。

产品照片第一版只维护图片类型、适用 SKU、图片说明、审核状态和是否允许引用，不直接驱动自动回复。资料体检接口应返回缺说明书、缺 SKU 图、价格过期、知识未审核、解析失败、信息冲突等状态。

## 安全和兼容性要求

- 所有接口使用 `/v1` 版本前缀，避免后续字段演进破坏旧接入方。
- 请求必须支持 `request_id` 幂等键，避免外部系统重试导致重复决策。
- 返回必须包含 `decision_id`，用于反馈、审计、消息追踪和问题排查。
- 鉴权第一版可使用 API Key 或 Bearer Token，后续再扩展到租户级密钥、签名和 IP 白名单。
- 日志中不保存 Cookie、二维码、短信验证码、完整买家敏感身份信息等会话材料。
- 客户 Admin 和系统 Admin 必须使用不同 Cookie / session 名、不同路由守卫和不同 API 鉴权域；客户后台 UI 不展示系统后台入口。
- 平台原始字段放入 JSONB 风格的 `raw` 或 `metadata` 字段，标准字段保持稳定。
- Markdown 审稿稿件和 LLM 生成的模拟问答不能直接作为自动回复知识源，必须经人工片段审核。
- 价格类回复必须引用外部系统当前有效价格快照；价格缺失、过期或冲突时不能自动报价。
- 外部动作请求必须带 `idempotency_key`，外部系统回调执行结果时也要回传 `action_id`，避免重复备注、重复改地址等副作用。
- Webhook / callback 必须支持签名校验、超时、重试和失败降级；没有成功结果前，Agent 不能向买家确认动作已完成。
- 补上下文回填必须带 `context_request_id` 和 `idempotency_key`；服务端以 `decision_id + context_request_id + idempotency_key` 聚合和去重。
- LangGraph checkpoint、Admin session、补上下文聚合状态都必须使用外部持久化存储，不能依赖单 API 实例内存。
- 单次问答等待预算最高 5 秒；超时仍缺关键上下文时返回 `candidate` 或 `handoff`，并在 trace 中记录降级原因。
- `GET /v1/message-traces/{decision_id}` 面向内部客服运营、技术排障和系统审计，不直接暴露给买家。

## 后续需改进的设计

### 1. 外部数据源 Connector

第一版由外部系统根据 `context_requests[]` 主动回填上下文，Agent 不直接拉客户内部系统。后续增加 `connector` 配置，让 Agent 在需要时主动查询外部系统：

```text
GET /v1/admin/connectors
POST /v1/admin/connectors
PATCH /v1/admin/connectors/{connector_id}
```

Connector 属于客户 Admin 店铺配置能力，不属于外部决策 token 能直接写入的 API。客户 Admin session 只能维护自己组织 / 店铺下的 Connector；系统 Admin 可在系统后台查看健康、审计和跨租户故障摘要，但不默认代替客户配置真实鉴权。

Connector 配置必须声明：

- `organization_id`、`store_id`、`provider`、`connector_id`。
- `auth_ref`：Secret Manager、Kubernetes Secret 或等价安全存储引用；不得传、返或记录真实 token。
- `capabilities[]`：按 `products`、`orders`、`rules`、`logistics` 声明主动查询能力。
- `operations[]`：`get`、`search`、`list_recent` 等稳定操作名。
- `timeout_ms`：单次查询超时，最高不超过 5000ms。
- `retry_policy`：最多 3 次，指数或固定退避；不得让单条客服消息无限等待。
- `circuit_breaker`：失败阈值、半开恢复窗口和当前 `circuit_state`。
- `failure_fallback`：失败后降级为 `context_request`、`candidate` 或 `handoff`。

Connector 运行规则：

- 同步请求体更小。
- Agent 可以按需刷新订单、物流和规则。
- 多个平台能复用同一套 Agent 决策流程。
- Connector 查询失败、超时、熔断打开或鉴权失效时，trace 必须记录 `CONNECTOR_UNAVAILABLE` 或 `CONNECTOR_CIRCUIT_OPEN`，再按 `failure_fallback` 降级。
- 不能因为查不到订单数据而让模型猜测订单状态。
- 第一版仍以 `context_requests[]` 回填为主；Connector 是后续主动查询增强，不改变同步主链路的最小接入要求。

### 2. 异步事件处理

当同步接口耗时不可控时，引入事件接口和任务状态：

```text
POST /v1/events/messages
GET /v1/tasks/{task_id}
```

`POST /v1/events/messages` 使用外部系统 API token，提交内容与 `POST /v1/reply-decisions` 保持同一字段语义，并额外支持 `callback_preference` 和 `expected_timeout_ms`。请求必须带 `request_id`；服务端按 `organization_id + store_id + request_id` 幂等。幂等键重复且 payload 一致时返回原 `task_id`，payload 不一致时返回 409 / `IDEMPOTENCY_CONFLICT`。

入队响应必须返回：

- `task_id`：异步任务 ID。
- `request_id`：外部幂等键。
- `decision_id`：若入队阶段已经创建决策则返回，否则任务运行后再关联。
- `status`：`queued`、`running`、`waiting_context`、`completed`、`failed`、`retrying`、`canceled` 或 `dead_lettered`。
- `poll_url`：`/v1/tasks/{task_id}`。
- `retry_after_ms`：建议轮询间隔。

`GET /v1/tasks/{task_id}` 轮询响应必须包含：

- `task_id`、`request_id`、`task_type`、`status`。
- `decision_id` 和 `trace_ref`，用于跳转 `GET /v1/message-traces/{decision_id}`。
- `decision` 摘要；未完成或无权限时为 `null`。
- `error`：失败时使用统一 `ErrorDetail`，不得包含 raw payload、请求头、Cookie 或 secret。
- `retry_count`、`max_retries`、`next_retry_at`、`created_at`、`updated_at`、`completed_at`。

失败和重试规则：

- 可重试错误包括短暂网络失败、Connector 超时、队列 Worker 临时不可用和 Webhook 5xx。
- 不可重试错误包括鉴权失败、schema 校验失败、租户权限不匹配和幂等冲突。
- 超过最大重试次数后任务进入 `failed` 或 `dead_lettered`，系统后台可通过任务排障接口查看摘要并在安全条件下重试。
- 异步任务不能绕过同步接口已有的规则闸门、trace、审计、脱敏和权限隔离。

第一版不强依赖异步，避免过早增加队列、任务调度和回调签名复杂度；实现优先级仍低于同步 `reply-decisions`、typed context refill、Admin 和评测门禁。

### 3. 回调机制

后续允许外部系统注册回调地址：

```text
POST /v1/webhook-subscriptions
GET /v1/webhook-subscriptions
PATCH /v1/webhook-subscriptions/{subscription_id}
DELETE /v1/webhook-subscriptions/{subscription_id}
```

可回调事件：

- `reply_decision.completed`
- `reply_decision.failed`
- `knowledge_entry.created`
- `feedback.processed`

Webhook 订阅使用外部系统 API token 管理，只能访问该 token 授权的组织 / 店铺。订阅字段包括 `subscription_id`、`organization_id`、`store_id`、`target_url`、`event_types[]`、`signing_algorithm`、`retry_policy`、`redaction_policy`、`status` 和 `secret_ref`。创建或轮换时可以一次性返回 `signing_secret`，后续查询只能返回 `secret_ref` 或摘要。

投递事件 envelope：

```json
{
  "event_id": "evt-001",
  "event_type": "reply_decision.completed",
  "occurred_at": "2026-06-12T10:15:06+08:00",
  "organization_id": "org-001",
  "store_id": "store-001",
  "decision_id": "decision-001",
  "request_id": "external-idempotency-key",
  "payload": {
    "action": "candidate",
    "trace_ref": "/v1/message-traces/decision-001"
  }
}
```

签名算法固定为 `hmac-sha256`：使用订阅 secret 对 `{timestamp}.{event_id}.{raw_body_sha256}` 计算 HMAC-SHA256，并通过 `X-Agent-Timestamp`、`X-Agent-Event-Id`、`X-Agent-Signature` 发送。接收方必须校验时间窗口和签名；重复 `event_id` 应幂等忽略。

重试和死信规则：

- 2xx 视为成功；408、429、5xx 可重试；4xx 除 408 / 429 外默认不可重试。
- 重试策略由 `max_attempts`、`initial_backoff_seconds`、`max_backoff_seconds` 和 `dead_letter_after_attempts` 控制。
- 超过死信阈值后写入死信记录，事件状态为 `dead_lettered`，系统后台只展示摘要和错误 code。
- Webhook payload 默认脱敏；不得包含完整买家身份、手机号、地址、Cookie、请求头、API token、Admin session 或 Connector secret。需要 raw payload 的排障必须走系统 Admin 审计权限，不通过 Webhook。

### 4. 规则版本和灰度

第一版可以用代码规则或简单规则表。后续需要支持：

```text
GET /v1/admin/rules/rule-sets
POST /v1/admin/rules/rule-sets
POST /v1/admin/rules/rule-sets/{rule_set_id}/dry-runs
POST /v1/admin/rules/rule-sets/{rule_set_id}/releases
```

客户 Admin 权限边界：

- 客户 Admin 维护自己组织 / 店铺的店铺级规则、灰度范围、回滚和 dry-run。
- 组织所有者、组织管理员、店铺管理员和规则运营可按角色写规则；只读审计只能查看。
- 高风险规则、自动回复比例提升、回滚和灰度扩大必须填写 `reason`，并记录 `audit_log_id`。
- 客户 Admin 不能修改系统级平台强制规则，也不能跨租户读取其他客户规则。

系统 Admin 权限边界：

- 系统 Admin 管理平台级强制规则、全局模板、发布质量和跨租户排障。
- 系统 Admin 不默认代替客户发布店铺规则；确需代操作时必须走系统审计、原因记录和敏感访问控制。

规则版本字段：

- `rule_set_id`、`rule_version`、`release_status`。
- `traffic_scope`：`all_store_traffic`、`percentage`、`platform`、`product_category` 或 `manual_sample`。
- `rollback_ref`：回滚目标历史 `rule_set_id` 或 `rule_version`。
- `approval`：审批人、审批时间和审批引用。
- `reason`：发布、灰度、暂停或回滚原因。
- `rules[]`：稳定 `rule_id`、`rule_type`、`priority`、`condition`、`action` 和 `risk_level`。

发布状态建议固定为 `draft`、`dry_run_passed`、`canary`、`active`、`paused`、`rolled_back`、`archived`。dry-run 可使用匿名化测试样本、评测 case 或历史决策回放引用，响应只返回命中规则、动作、风险和差异摘要，不返回真实买家敏感内容。

这能避免规则变更后影响所有店铺，也便于解释“为什么这条消息自动回复/转人工”。

### 5. 自动回复门槛治理

后续自动回复门槛应从固定阈值演进为按场景配置：

- 商品参数类问题可以较早自动化。
- 价格类问题必须依赖当前有效 `product_price_snapshot`。
- 物流状态类问题需要订单数据可靠。
- 售后、退款、投诉、承诺类问题默认人工确认。
- 新商品、新店铺、新规则刚上线时应降低自动回复比例。

所有自动回复都要记录命中的规则、知识来源、置信度和风险标记。

### 6. 学习与评估闭环

后续需要把人工反馈转成可评估数据：

- 候选采用率。
- 人工修改幅度。
- 自动回复后追问率。
- 转人工原因分布。
- 高风险误判率。
- 店铺、平台、商品维度的效果对比。
- 商品资料覆盖率、Markdown 解析失败率、知识片段审核通过率、模拟问答回归通过率。

这些指标决定哪些场景可以从“候选回复”升级到“自动回复”。

### 7. 多租户和权限

后续要把组织、店铺、平台账号和客服账号分开：

- 一个组织可有多个店铺。
- 一个店铺可接多个平台账号。
- 不同店铺的知识、规则、订单和会话必须隔离。
- API Key 应绑定组织或店铺权限。

第一版即使不完整实现，也应在字段设计中保留 `organization_id`、`store_id` 和 `platform`。

## 第一版落地边界

第一版建议只实现以下闭环：

1. 外部系统调用 `POST /v1/reply-decisions`，只传买家消息、最小会话和可选已有上下文。
2. Agent 直接返回 `auto_reply` / `candidate` / `handoff`，或返回 `context_requests[]` / `action_request`。
3. 外部系统按 `context_requests[]` 并行调用 products / orders / logistics / rules 回填接口；动作执行后调用 `actions/results`。
4. Agent 在 5 秒等待预算内聚合同一 `decision_id` 的上下文，输出可答复内容、动作请求或人工介入。
5. 人工处理后调用 `POST /v1/feedback/human-replies`。
6. Agent 保存决策记录、补上下文 trace、动作结果和人工反馈，用于后续知识沉淀和评估。

不建议第一版就实现复杂 Connector、消息队列、回调订阅、规则后台和自动训练。接口字段先预留，能力分阶段补齐。
