# 开发交接记录

本文记录会影响开发定位的最新文档变化和新会话入口。它不是新的架构来源；第一版范围以 [Development Readiness](development-readiness.md) 为准，接口契约以 [OpenAPI Contract](openapi.yaml) 为准，系统流程以 [System Architecture](system-architecture.md) 和 [System Architecture HTML](system-architecture.html) 为准。

## 最近文档更新

### 2026-06-18

- Customer Admin Web 已整改为三段式入口：客户 host `/` 匿名展示公开宣传页，`/login` 展示客户专用登录页，`/admin` 只在 `/v1/admin/auth/me` 校验成功后渲染客户后台 shell；未登录 `/admin` 重定向 `/login`。
- 客户公开页和登录页不挂载后台侧栏，不展示系统后台 nav、tab、switch 或 CTA；系统后台仍由独立 host 和 `/v1/system-admin/auth/me` 鉴权域承载。

- 实现客户后台 / 系统后台拆站基础：Admin Web 按 Host 固定 customer / system 模式，不再提供站内后台类型切换；客户 host 只刷新 `/v1/admin/auth/me`，系统 host 只刷新 `/v1/system-admin/auth/me`。
- Helm chart / dev values 已显式表达 `admin.ecommerce-cs-agent-dev.fcihome.com` 和 `system-admin.ecommerce-cs-agent-dev.fcihome.com`，Admin Ingress 同一 TLS secret 下渲染两个 host；release gate 报告拆分 API、Customer Admin、System Admin 三路 health。
- 现场 DNS 验证显示 `system-admin.ecommerce-cs-agent-dev.fcihome.com` 已解析到 `47.113.204.168`，但当前线上 HTTPS 仍返回 Traefik default cert 且 `/health` 为 404；不能把 DNS 已配置误判为 Ingress/TLS 已上线。

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
