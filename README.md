# Ecommerce Customer Service Agent

电商客服 Agent 新项目启动文档。

## 项目目标

当前客服系统覆盖多个电商平台，主要依赖人工回复。各平台可以通过 API 接入自动回复，每个平台商品都有商品简介和相关信息，但历史人工回复数据暂时不足。

本项目目标是建设一套平滑过渡的客服 Agent：

1. 人工回复为主，Agent 提供候选回复。
2. 人工回复后，Agent 学习人工回复内容。
3. Agent 自动回复确定性问题，无法确定或高风险问题转人工。

最终目标是让人工回复量持续下降，直到大部分低风险、重复性问题可自动处理。

## 核心设计原则

- 不让大模型直接决定一切，自动回复必须经过规则闸门。
- 先做客服副驾，再做半自动客服，最后做自动客服。
- 人工回复不是简单存成聊天记录，而是沉淀为可检索、可评估、可复用的知识资产。
- 决策过程必须可追踪：为什么给候选、为什么自动回复、为什么转人工，都要留记录。
- 商品、订单、平台、店铺、客服账号、会话上下文要结构化存储，避免只存问答文本。

## 推荐初始技术方向

- 主存储：PostgreSQL。
- 半结构化字段：PostgreSQL JSONB。
- 语义检索：pgvector 起步。
- 决策闸门：应用代码中的规则表起步，后续可演进到 OPA。
- Agent/RAG：先用简单服务流水线，后续复杂后再考虑 LangGraph、LlamaIndex 或 Haystack。
- 原始归档和训练导出：JSONL 或对象存储。
- 指标分析：数据量上来后再引入 ClickHouse。

## 项目文档

- [Session Transcript](docs/session-transcript.md)
- [Technical Options](docs/technical-options.md)
- [HTTP API Design](docs/http-api-design.md)
- [System Architecture](docs/system-architecture.md)
- [Application Technology Architecture](docs/application-technology-architecture.md)
- [System Architecture HTML](docs/system-architecture.html)
