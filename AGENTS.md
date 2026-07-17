<!-- CODEGRAPH_START -->
## CodeGraph

This project has a CodeGraph MCP server (`codegraph_*` tools) configured. CodeGraph is a tree-sitter-parsed knowledge graph of every symbol, edge, and file. Reads are sub-millisecond and return structural information grep cannot.

### When to prefer codegraph over native search

Use codegraph for structural questions: what calls what, what would break, where a symbol is defined, or what a signature/source looks like. Use native grep/read only for literal text queries or after a specific file is already known.

| Question | Tool |
|---|---|
| Where is X defined? / Find symbol X | `codegraph_search` |
| What calls Y? | `codegraph_callers` |
| What does Y call? | `codegraph_callees` |
| What would break if Z changes? | `codegraph_impact` |
| Show Y source/signature | `codegraph_node` |
| Get focused task context | `codegraph_context` |
| Inspect several related symbols/files | `codegraph_explore` |
| List files under a path | `codegraph_files` |
| Check index health | `codegraph_status` |

If `.codegraph/` is missing or the server says the project is not initialized, ask before running `codegraph init -i`.
<!-- CODEGRAPH_END -->

## Development Handoff

- Development and documentation sessions must read `docs/development-handoff.md` before planning or editing project docs, contracts, Admin behavior, deployment, testing, or implementation scope.
- After completing a documentation change that affects implementation scope, API contracts, deployment, testing, Admin boundaries, or security rules, add a short dated entry at the top of `docs/development-handoff.md`.
- `docs/development-handoff.md` is a routing and change-orientation document, not a new architecture source. Keep architecture truth in the documents named below.

## Architecture Documents

Keep architecture content in one source file.

### Source of truth

- `docs/system-architecture.html` is the only interactive architecture document. It contains architecture views, nodes, links, labels, summaries, details, and the right-side database schema panel.
- Do not add generated architecture duplicates for the same content. Update `docs/system-architecture.html` directly.
- `docs/customer-admin-design.md` is the source document for customer Admin backend design. Keep detailed public landing/login entry, tenant/store switching, roles, settings, product-content maintenance, knowledge review, rule configuration, action capability configuration, and audit requirements there.
- Architecture documents may summarize customer Admin behavior, but they should link to `docs/customer-admin-design.md` instead of duplicating the full Admin design.

### Admin design documents

- `docs/customer-admin-design.md` defines the customer-facing Admin backend for tenant users who maintain product content, knowledge reviews, store rules, action capabilities, and customer-side audit queries.
- `docs/system-admin-design.md` defines the internal system Admin backend for platform operators, technical support, system administrators, release managers, and security auditors.
- `docs/system-admin-ui-prototype.html` is the static UI prototype for the system Admin backend. Use it to keep implementation layout, navigation grouping, visual density, component styling, and interaction patterns consistent with the approved design.
- Keep customer Admin and system Admin responsibilities separate: customer Admin manages a tenant's own business configuration; system Admin manages tenant onboarding, cross-tenant readiness, operational troubleshooting, global templates, system health, release quality, and platform-level audit.

### Required workflow after architecture changes

After changing `docs/system-architecture.html` in any way that affects views, processes, node labels, links, database schema, or details:

```bash
node docs/scripts/validate-x6-architecture-runtime.mjs
node docs/scripts/validate-business-flow-x6-labels.mjs
```

### API and business-flow diagram coupling

- When changing `/v1/reply-decisions`, `context_requests[]`, typed context refill APIs, action result APIs, decision statuses, or the external-system interaction flow, update these documents in the same change:
  - `docs/http-api-design.md`
  - `docs/system-architecture.md`
  - `docs/application-technology-architecture.md`
  - `docs/system-architecture.html`
- When changing LangGraph / Decision Orchestrator design, graph state, checkpoint storage, `thread_id`, `graph_version`, interrupt/resume behavior, or node-level trace behavior, update the same documents plus `docs/technical-options.md`.
- In `docs/system-architecture.html`, keep the API text and the `#api-business-flow` diagram synchronized. Update `apiDocumentation.quickStart.businessFlow`, API endpoint definitions, and `initBusinessFlowDiagram()` `flowNodes` / `flowEdges` together.
- The `#api-business-flow` diagram must use right-angle X6 edges for process links. Do not introduce diagonal business-flow connectors when updating nodes, labels, or branches.
- After changing the business-flow diagram, update `docs/scripts/validate-business-flow-x6-labels.mjs` if the intended nodes, edges, labels, routing style, or layout expectations changed.

### Database model rules

- Data model table nodes must show a Chinese short name plus the English table name, for example `决策记录\nDECISION_RECORD`.
- The right-side `databaseSchema` section in `docs/system-architecture.html` must remain the detailed database design reference.
- If a table is added, renamed, or removed, update `dataModel.nodes`, `databaseSchema`, and validation assertions together.

### Customer Admin design rules

- Customer Admin is a first-version required capability, not a future-only module.
- When changing public landing entry, Admin login routes, session boundaries, roles, tenant/store permissions, settings, product-content maintenance, knowledge review, rule configuration, action capability configuration, or audit behavior, update `docs/customer-admin-design.md` in the same change.
- Keep `docs/system-architecture.md`, `docs/application-technology-architecture.md`, `docs/http-api-design.md`, and `docs/system-architecture.html` linked to the Admin design when their summaries mention Admin behavior.

### Admin UI/UX design rules

- The public landing page is Notion-led: black/neutral palette, generous whitespace, clear AI Agent narrative, product capability modules, trust proof, product previews, and a black primary CTA.
- The logged-in customer Admin must not become Notion-like. It remains an IBM / Carbon-style dense enterprise console with scan-friendly tables, queues, forms, low shadows, and hairline dividers.
- Ant Design may be used as the component capability layer, but it is not the visual style source. Final Admin visuals must be controlled by project theme tokens, custom CSS, and the project-owned visual baseline.
- When changing public landing pages, login pages, Admin shell, tables, forms, review queues, or configuration screens, update `docs/customer-admin-design.md` in the same change and keep architecture summaries consistent when they mention UI/UX rules.
- External websites and `DESIGN.md` files are reference material only. Do not copy their brands, Logo, licensed fonts, assets, copywriting, rounded-corner language, or brand-specific semantics into this project.

### Admin Web live hosts and UI/UX review rules

- Customer Admin live host is `https://admin.ecommerce-cs-agent-dev.fcihome.com`; System Admin live host is `https://system-admin.ecommerce-cs-agent-dev.fcihome.com`.
- `ACS` is the shorthand for the customer-facing AI customer-service system at `https://admin.ecommerce-cs-agent-dev.fcihome.com`; when the user says ACS in this project, treat it as Customer Admin, not System Admin or the public API host.
- `SACS` is the shorthand for the System Admin backend at `https://system-admin.ecommerce-cs-agent-dev.fcihome.com`; when the user says SACS in this project, treat it as System Admin, not Customer Admin or the public API host.
- Customer Admin route guards must only call `/v1/admin/auth/me`; System Admin route guards must only call `/v1/system-admin/auth/me`.
- Customer Admin uses `agent_admin_session`; System Admin uses `agent_system_admin_session`. Do not make either site probe, reuse, or accept the other site's session.
- Dev public routing currently reuses the existing K3s `frp-system/bpg-frpc` `cs-agent-dev-http` proxy. Do not add a second frpc proxy or configure `type=https` for this split unless the deployment architecture changes deliberately.
- The outer ai-agent Traefik / frps layer is expected to route API, Customer Admin, and System Admin hostnames. If System Admin health or TLS fails publicly while in-cluster service health passes, check the outer host route before changing the app chart.
- For professional UI/UX review or remediation, inspect both Admin hosts at desktop `1440x900` and mobile `390x844`, and record whether evidence came from live inspection, screenshots, or code review.
- Use `docs/admin-web-ui-ux-audit.md` as the current Admin Web UI/UX remediation backlog when present. If a branch does not contain it yet, preserve the same priorities: customer public landing, isolated login pages without live test defaults, mobile navigation, and accessibility/state polish.
- Before claiming an Admin Web UI change is done, verify no horizontal overflow on mobile, no Customer/System cross-entry appears, and the relevant host still calls only its own auth/me endpoint.

### Admin login test credentials and storage state

- Never print, paste, commit, or put in docs real live Admin passwords, Cookie values, Secret values, kubeconfig content, Authorization headers, or generated browser storage state.
- Admin initial account values come from runtime Secret keys: customer uses `ADMIN_INITIAL_EMAIL` and `ADMIN_INITIAL_PASSWORD_HASH`; system uses `SYSTEM_ADMIN_INITIAL_EMAIL` and `SYSTEM_ADMIN_INITIAL_PASSWORD_HASH`, with code-level fallback to the customer initial account only when system-specific keys are absent.
- A stored password hash is not a recoverable password. Only `plain:<password>` values can be converted to a plaintext password for local smoke tests. If the runtime Secret stores a hash, obtain the plaintext through an approved Secret channel and pass it via environment variables for that one command.
- Use `scripts/admin_web_login_state.mjs` when available to create Playwright-compatible login state for UI testing. It must write only local `0600` files under `/tmp` or another ignored path, and those files must be deleted after testing.
- When using curl or Playwright for Admin login tests, write cookies to temporary files or browser storage state; do not print `Set-Cookie`, raw Cookie headers, passwords, or token-bearing JSON to chat, logs, docs, PR descriptions, or test snapshots.
- If an Admin login helper is unavailable on the current branch, follow the same behavior: read Secret key names only, keep plaintext in environment variables, validate `/v1/admin/auth/me` and `/v1/system-admin/auth/me`, and redact all credential-bearing outputs.

### System independence rules

- The customer service Agent is an independent system. Any external system can integrate through the public Agent APIs without depending on `open_erp_agent`.
- Do not depend on `open_erp_agent` login state, tenant tables, store tables, WeChat users, sessions, tokens, Admin UI, or server internals for Agent Admin login, tenant resolution, permissions, SSO, or runtime behavior.
- ERP systems are only design references or example external integrators. Do not describe ERP as the default identity provider, default upstream, required deployment component, or source of truth for Agent data.
- External-system integration, Admin login, tenant/store permissions, and SSO design must remain provider-agnostic. Use generic external references and stable Agent-owned identifiers instead of vendor-specific or project-specific identity fields.
- If documentation mentions ERP, it must be phrased as one possible external-system example and must not alter the standalone Agent API contract or Admin ownership model.
- Public landing pages, login pages, Admin routes, and Admin sessions belong to the customer service Agent itself. They must not use ERP or any external system login state as the default entry, identity source, or session authority.

## 开发规则
- 开发的应用,后台,服务,要可支持 k8s 无状态 部署
- 需要持续存储的内容,遵循 k8s 设计规范

## CI/CD 安全门禁

- 当前 PR 阶段先使用 GitHub CodeQL / GitHub Advanced Security 做 SAST 门禁，workflow 在 `.github/workflows/codeql.yml`。
- 排查 PR 被拦截时，先看 `CodeQL SAST` job，再看 `Notify security gate blocked` 邮件通知 job，最后确认 GitHub Branch Protection 是否把 CodeQL check 设为 required。
- 仓库公开后，CodeQL workflow 上传 SARIF 到 GitHub Code Scanning，并继续解析 SARIF 让 alert 阻断 job；如果仓库改回 private 且未启用 Code Security，上传会失败。
- 邮件拦截通知发送到 `46164072@qq.com`；SMTP 连接信息必须放在 GitHub Secrets：`SMTP_HOST`、`SMTP_PORT`、`SMTP_USERNAME`、`SMTP_PASSWORD`、`MAIL_FROM`、`SECURITY_NOTIFY_TO`。不要把 SMTP 密钥写入 Git、文档或聊天记录。
- SonarQube、Snyk/Dependabot、镜像扫描、Helm/K8s 配置扫描是后续 CI/CD 优化项，暂不作为当前第一阶段 required check。

## 镜像发布规则

- 不要从 Codex 本机执行 `docker push` 发布业务镜像。API/Admin 镜像发布走 GitHub Actions workflow：`.github/workflows/publish-images.yml`。
- GHCR 镜像名为 `ghcr.io/liuyenhui/ecommerce-cs-agent-api:<tag>` 和 `ghcr.io/liuyenhui/ecommerce-cs-agent-admin:<tag>`，作为备份和 GitHub 原生发布记录。
- 国内 dev/K8s 默认拉取阿里云镜像：`registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-api:<tag>` 和 `registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-admin:<tag>`。
- `Publish Images` 在有 GitHub Secrets `ALIYUN_REGISTRY_USERNAME`、`ALIYUN_REGISTRY_PASSWORD` 时同时推送阿里云 `:<tag>`、`:sha-<commit>`、`:deploy`；没有这两个 Secrets 时只推 GHCR。
- 需要发布指定 dev tag 时，推送分支 `codex/publish-<tag>`，workflow 会把分支后缀作为镜像 tag；也可以在 GitHub Actions 手动运行 `Publish Images` 并输入 `tag`。
- `Publish Images` 必须先通过 Python tests、Helm lint、Helm template，再构建并推送 API/Admin 镜像。
- K8s dev 使用 Helm values 中的 `aliyun-registry-auth` 拉阿里云镜像，保留 `ghcr-auth` 作为备份。发布后创建临时 pull-check Pod，设置 `imagePullPolicy: Always` 验证远端 tag 可拉取；验证完成后删除临时 Pod。
- Watchtower 方案仅适用于服务器 docker compose 自动更新；本项目 dev 环境是 Kubernetes/Helm，不使用 Watchtower，部署由 Helm/GitOps 更新 image tag 完成。

## Public Repository Safety

- This repository may be public. Treat every tracked file as world-readable before committing or pushing.
- Never commit `.env`, kubeconfig files, cloud credentials, SMTP passwords, API keys, database URLs with passwords, GHCR tokens, LLM keys, MinIO keys, JWT/session secrets, private certificates, or production customer data.
- Keep real secrets only in GitHub Secrets, Kubernetes Secrets, or an approved external secret manager. Documentation may name secret keys, namespaces, and retrieval paths, but must not contain secret values.
- Before any commit or push that touches deployment, CI/CD, config, or docs, run a targeted secret check with `git diff --cached` and `rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET"`.
- Do not publish real customer files, exported JSONL, evaluation datasets containing private data, screenshots with tokens, or logs containing request headers/cookies.
- Public examples must use placeholders such as `<from-secret>`, `<redacted>`, or fake local-only values.
