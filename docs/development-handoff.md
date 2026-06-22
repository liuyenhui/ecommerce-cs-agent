# 开发交接记录

本文记录会影响开发定位的最新文档变化和新会话入口。它不是新的架构来源；第一版范围以 [Development Readiness](development-readiness.md) 为准，接口契约以 [OpenAPI Contract](openapi.yaml) 为准，系统流程以 [System Architecture](system-architecture.md) 和 [System Architecture HTML](system-architecture.html) 为准。

## 最近文档更新

### 2026-06-22

- 补充 `system-admin.ecommerce-cs-agent-dev.fcihome.com` 的公网入口排障路径：系统后台域名复用 `frp-system/bpg-frpc` 的 `cs-agent-dev-http` HTTP vhost，需要同时检查 ai-agent 外层 Traefik `frps_vhost` Host rule、K3s frpc `customDomains`、Ingress host 和 TLS SAN。

### 2026-06-21

- GitHub Actions 发布、部署、PR Helm 检查和 CodeQL 失败通知升级到 Node 24 运行时对应的 action 版本，不再依赖触发 Node.js 20 deprecation warning 的旧 action 主版本。
- 更新客户公开首页方向：`admin.ecommerce-cs-agent-dev.fcihome.com` 的 `/` 是公开宣传页和客户登录入口，对外统一使用“AI / AI 客服”白话叙事，不把 Agent 概念、系统后台入口或 ERP 身份源暴露给客户。
- 公开首页首屏、产品演示轮播和“怎么工作”动效围绕“商品信息管好了，AI 客服才答得准。”以及“上传商品说明书 → AI 学习 → 模拟问答 → AI 自动回复”主流程实现；客户 Admin 登录后仍保持 IBM / Carbon 式密集企业控制台。

### 2026-06-19

- 新增 [Admin Web UI/UX 审计与整改拆分](admin-ui-ux-audit.md)：基于 Chrome live 登录检查 customer/system Admin 的桌面与移动页面，记录 P0/P1/P2 UI/UX 问题，并拆分为可分发给开发线程的整改 prompts。

### 2026-06-18

- `AGENTS.md` 增补 Admin Web live host、Customer/System auth 边界、FRP/TLS 排查顺序、UI/UX 审计视口和 Admin 登录测试凭据 / storageState 安全规则，作为后续开发线程的项目级操作约束。
- 新增 [Admin Web UI/UX 审计与整改计划](admin-web-ui-ux-audit.md)，记录客户 Admin / 系统 Admin live 未登录页的桌面与移动端审计结论、登录信息安全边界、整改优先级和可分发给 Codex 开发线程的 prompts。
- 复验 dev 公开入口：`system-admin.ecommerce-cs-agent-dev.fcihome.com` 已解析到 `47.113.204.168`，HTTPS 证书 SAN 已覆盖 API / Customer Admin / System Admin，`/health` 返回 `200 ok`；Playwright 运行时验证 customer host 只请求 `/v1/admin/auth/me`，system host 只请求 `/v1/system-admin/auth/me`。
- 外层 ai-agent Traefik / frps 已追加 system-admin Host 并重启生效；K3s 侧继续复用 `frp-system/bpg-frpc` 的 `cs-agent-dev-http` proxy，不新增 frpc，也不配置 `type=https`。

- 实现客户后台 / 系统后台拆站基础：Admin Web 按 Host 固定 customer / system 模式，不再提供站内后台类型切换；客户 host 只刷新 `/v1/admin/auth/me`，系统 host 只刷新 `/v1/system-admin/auth/me`。
- Helm chart / dev values 已显式表达 `admin.ecommerce-cs-agent-dev.fcihome.com` 和 `system-admin.ecommerce-cs-agent-dev.fcihome.com`，Admin Ingress 同一 TLS secret 下渲染两个 host；release gate 报告拆分 API、Customer Admin、System Admin 三路 health。

- 固定客户后台和系统后台的 Web 站点边界：客户后台使用 `admin.ecommerce-cs-agent-dev.fcihome.com`，系统后台使用 `system-admin.ecommerce-cs-agent-dev.fcihome.com` 作为目标域名，`ops-admin.ecommerce-cs-agent-dev.fcihome.com` 仅作为可选别名。
- 两个后台必须使用不同登录页、Cookie / session 名、路由守卫和 API 鉴权域；客户后台 UI 不展示“系统后台”入口，系统后台不得伪装客户用户调用客户 Admin API。
- 新增本文作为开发和文档新会话的第一交接入口，并在 [AGENTS](../AGENTS.md)、[README](../README.md) 和 [Development Readiness](development-readiness.md) 建立入口。

## 新会话优先阅读顺序

1. [AGENTS](../AGENTS.md)：项目级规则、架构文档维护要求、安全边界和提交前检查。
2. [Development Handoff](development-handoff.md)：最近影响开发的文档更新和交接提示。
3. [Development Readiness](development-readiness.md)：第一版必须实现、暂不实现、验收命令和 API 覆盖状态。
4. [Implementation Plan](implementation-plan.md)：从工程骨架、数据库、鉴权、API、Admin、测试到部署的实现顺序。
5. [OpenAPI Contract](openapi.yaml)：机器可读 API 契约、schema、错误码、权限和分页口径。
6. [Testing](testing.md)、[CI/CD](ci-cd.md)、[Deployment](deployment.md)、[Deployment Artifacts](deployment-artifacts.md)、[Runbook](runbook.md)：测试、发布、部署工件和排障入口。

## 开发新线程启动提示

可复制给新的开发会话：

```text
请先读取 AGENTS.md、docs/development-handoff.md、docs/development-readiness.md、docs/implementation-plan.md 和 docs/openapi.yaml。以 handoff 和 readiness 作为当前开发入口，不重新展开架构争论；按第一版必须实现范围推进，并保持客户后台和系统后台的 Web 站点、登录页、Cookie/session、路由守卫、API 鉴权域完全隔离。若修改影响开发范围、API、部署、测试、后台边界或安全规则的文档，完成后在 docs/development-handoff.md 顶部追加一条简短记录。
```

## 维护规则

- 只记录影响开发定位、实现范围、API 契约、部署验收、测试门禁、后台边界或安全规则的文档变化。
- 不记录纯格式调整、错别字修复或不影响实现的措辞优化。
- 新记录追加在“最近文档更新”顶部，使用日期标题和 1-3 条短 bullet。
- 不写真实 token、Secret、客户数据、生产 payload 或完整 Authorization header。
