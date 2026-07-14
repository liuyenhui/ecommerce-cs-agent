import React from "react";
import { systemApi } from "../system-api";
import type { JsonRecord } from "../../../shared/types";
import type { LlmBreakdown, LlmInvocation, LlmProvider, LlmRoute, LlmUsageFilters, LlmUsagePoint, LlmUsageSummary, LlmVersion } from "../system-types";
import { PaginationControls } from "./PaginationControls";

type Tab = "config" | "usage" | "versions" | "audit";
const tabs: Array<[Tab, string]> = [["config", "配置与路由"], ["usage", "调用与成本"], ["versions", "版本记录"], ["audit", "变更审计"]];
type UsageState = { kind: "idle" | "loading" } | { kind: "error"; message: string } | { kind: "empty" | "success"; data: LlmUsageSummary };
const idempotency = (prefix: string) => `${prefix}-${crypto.randomUUID()}`;
const errorText = (error: unknown) => error instanceof Error && error.message.startsWith("409 ") ? "配置已被其他管理员更新，请重新加载" : (error instanceof Error ? error.message : String(error));
const money = (micros: number, currency: string) => `${currency} ${(micros / 1_000_000).toFixed(6)}`;

const WRITE_ROLES = new Set(["super_admin", "release_admin"]);
const TEST_ROLES = new Set(["super_admin", "release_admin", "technical_support"]);

export function validateLlmRoute(route: LlmRoute): string | null {
  const finite = (value: number) => Number.isFinite(value);
  if (!finite(route.temperature) || route.temperature < 0 || route.temperature > 2) return "temperature 必须在 0–2";
  for (const [label, value, min, max] of [
    ["max_output_tokens", route.max_output_tokens, 1, 1_000_000], ["timeout_seconds", route.timeout_seconds, 1, 300],
    ["max_retries", route.max_retries, 0, 20], ["circuit_breaker_threshold", route.circuit_breaker_threshold, 1, 10_000],
    ["recovery_probe_seconds", route.recovery_probe_seconds, 1, 86_400]
  ] as Array<[string, number, number, number]>) {
    if (!finite(value) || !Number.isInteger(value) || value < min || value > max) return `${label} 必须是 ${min}–${max} 的整数`;
  }
  return null;
}

export function LlmGovernancePage({ roles = ["super_admin"] }: { roles?: string[] }) {
  const [tab, setTab] = React.useState<Tab>("config");
  const [providers, setProviders] = React.useState<LlmProvider[]>([]);
  const [organizationId, setOrganizationId] = React.useState("");
  const [versions, setVersions] = React.useState<LlmVersion[]>([]);
  const [versionPage, setVersionPage] = React.useState({ has_more: false, next_cursor: null as string | null });
  const [selectedId, setSelectedId] = React.useState("");
  const [routes, setRoutes] = React.useState<LlmRoute[]>([]);
  const [dirty, setDirty] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [busy, setBusy] = React.useState("");
  const [usageState, setUsageState] = React.useState<UsageState>({ kind: "idle" });
  const [points, setPoints] = React.useState<LlmUsagePoint[]>([]);
  const [breakdown, setBreakdown] = React.useState<LlmBreakdown[]>([]);
  const [scenarioBreakdown, setScenarioBreakdown] = React.useState<LlmBreakdown[]>([]);
  const [failureBreakdown, setFailureBreakdown] = React.useState<LlmBreakdown[]>([]);
  const [invocations, setInvocations] = React.useState<LlmInvocation[]>([]);
  const [invocationPage, setInvocationPage] = React.useState({ has_more: false, next_cursor: null as string | null });
  const [audit, setAudit] = React.useState<{ items: JsonRecord[]; page: { page: number; page_size: number; total: number } }>({ items: [], page: { page: 1, page_size: 20, total: 0 } });
  const [filters, setFilters] = React.useState<LlmUsageFilters>({});
  const [providerEditor, setProviderEditor] = React.useState(false);
  const [editingProvider, setEditingProvider] = React.useState<LlmProvider | null>(null);
  const [draftEditor, setDraftEditor] = React.useState(false);
  const controller = React.useRef<AbortController | null>(null);
  const selected = versions.find((item) => item.version_id === selectedId) || versions.find((item) => item.status === "draft") || versions[0];
  const canWrite = roles.some((role) => WRITE_ROLES.has(role));
  const canTest = roles.some((role) => TEST_ROLES.has(role));
  const moveTab = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    const key = event.key; if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(key)) return;
    event.preventDefault(); const nextIndex = key === "Home" ? 0 : key === "End" ? tabs.length - 1 : (index + (key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    setTab(tabs[nextIndex][0]); document.getElementById(`llm-tab-${tabs[nextIndex][0]}`)?.focus();
  };

  React.useEffect(() => {
    const next = new AbortController(); controller.current = next;
    systemApi.llmProviders(next.signal).then((data) => setProviders(data.items)).catch((error) => { if (!next.signal.aborted) setMessage(errorText(error)); });
    return () => next.abort();
  }, []);

  React.useEffect(() => {
    if (!selected) return;
    setSelectedId(selected.version_id);
    setRoutes(selected.routes.map(({ route_id: _routeId, revision: _revision, ...route }) => route));
    setDirty(false);
  }, [selected?.version_id, selected?.revision]);

  async function loadVersions() {
    if (!organizationId.trim()) { setMessage("请输入组织 ID"); return; }
    controller.current?.abort(); const next = new AbortController(); controller.current = next;
    setBusy("versions"); setMessage(""); setVersions([]); setVersionPage({ has_more: false, next_cursor: null }); setSelectedId(""); setRoutes([]); setDirty(false);
    try { const data = await systemApi.llmVersions(organizationId.trim(), undefined, next.signal); setVersions(data.items); setVersionPage(data.page_info); }
    catch (error) { if (!next.signal.aborted) setMessage(errorText(error)); }
    finally { if (!next.signal.aborted) setBusy(""); }
  }

  async function loadMoreVersions() {
    if (!versionPage.next_cursor) return;
    const data = await systemApi.llmVersions(organizationId.trim(), versionPage.next_cursor);
    setVersions((items) => [...items, ...data.items]); setVersionPage(data.page_info);
  }

  async function loadUsage() {
    controller.current?.abort(); const next = new AbortController(); controller.current = next;
    setBusy("usage"); setMessage(""); setUsageState({ kind: "loading" }); setPoints([]); setBreakdown([]); setScenarioBreakdown([]); setFailureBreakdown([]); setInvocations([]); setInvocationPage({ has_more: false, next_cursor: null });
    try {
      const [summary, series, byModel, byScenario, byFailure, calls] = await Promise.all([
        systemApi.llmUsageSummary(filters, next.signal), systemApi.llmUsageTimeseries(filters, next.signal),
        systemApi.llmUsageBreakdown(filters, "model", next.signal), systemApi.llmUsageBreakdown(filters, "scenario", next.signal),
        systemApi.llmUsageBreakdown({ ...filters, status: "failed" }, "error_code", next.signal), systemApi.llmInvocations(filters, undefined, next.signal)
      ]);
      setUsageState({ kind: summary.calls === 0 ? "empty" : "success", data: summary }); setPoints(series.items); setBreakdown(byModel.items); setScenarioBreakdown(byScenario.items); setFailureBreakdown(byFailure.items); setInvocations(calls.items); setInvocationPage(calls.page_info);
    } catch (error) { if (!next.signal.aborted) setUsageState({ kind: "error", message: `用量数据加载失败：${errorText(error)}` }); }
    finally { if (!next.signal.aborted) setBusy(""); }
  }

  async function loadMoreInvocations() {
    if (!invocationPage.next_cursor) return;
    const data = await systemApi.llmInvocations(filters, invocationPage.next_cursor);
    setInvocations((items) => [...items, ...data.items]); setInvocationPage(data.page_info);
  }

  React.useEffect(() => {
    if (tab === "usage" && usageState.kind === "idle") void loadUsage();
    if (tab === "audit" && audit.page.total === 0) {
      controller.current?.abort(); const next = new AbortController(); controller.current = next;
      systemApi.audit({ action_prefix: "llm.", page: 1, page_size: 20 }, next.signal).then(setAudit).catch((error) => { if (!next.signal.aborted) setMessage(errorText(error)); });
    }
    return () => controller.current?.abort();
  }, [tab]);

  async function loadAuditPage(page: number) {
    controller.current?.abort(); const next = new AbortController(); controller.current = next;
    try { setAudit(await systemApi.audit({ action_prefix: "llm.", page, page_size: 20 }, next.signal)); }
    catch (error) { if (!next.signal.aborted) setMessage(errorText(error)); }
  }

  function patchRoute(index: number, patch: Partial<LlmRoute>) { setRoutes((items) => items.map((item, i) => i === index ? { ...item, ...patch } : item)); setDirty(true); }
  async function saveRoutes() {
    if (!selected || selected.status !== "draft" || !dirty) return;
    const invalid = routes.map(validateLlmRoute).find(Boolean);
    if (invalid) { setMessage(invalid); return; }
    const reason = window.prompt("请输入保存草稿原因")?.trim(); if (!reason) return;
    setBusy("save");
    try { const updated = await systemApi.replaceLlmRoutes(selected.version_id, routes, selected.revision, reason, idempotency("routes")); setVersions((items) => items.map((item) => item.version_id === updated.version_id ? updated : item)); setDirty(false); setMessage("草稿已保存，运行版本未改变"); }
    catch (error) { setMessage(errorText(error)); }
    finally { setBusy(""); }
  }

  async function validateDraft() {
    if (!selected || selected.status !== "draft") return;
    const reason = window.prompt("请输入验证草稿原因")?.trim(); if (!reason) return;
    setBusy("validate");
    try { const updated = await systemApi.validateLlmVersion(selected.version_id, { expected_revision: selected.revision, reason, idempotency_key: idempotency("validate") }); setVersions((items) => items.map((item) => item.version_id === updated.version_id ? updated : item)); setMessage("草稿已通过验证，可进入评测发布流程"); }
    catch (error) { setMessage(errorText(error)); }
    finally { setBusy(""); }
  }

  async function connectionTest(provider: LlmProvider) {
    if (!selected || selected.status !== "draft") { setMessage("请先加载草稿版本再测试连接"); return; }
    const reason = window.prompt("请输入连接测试原因")?.trim(); if (!reason) return;
    setBusy(`test-${provider.provider_id}`); setMessage("连接测试进行中…");
    try { const result = await systemApi.testLlmProvider(provider.provider_id, { config_version_id: selected.version_id, reason, idempotency_key: idempotency("connection-test") }); setMessage(`连接测试${result.status === "passed" ? "通过" : "失败"}${result.latency_ms !== undefined ? `，耗时 ${result.latency_ms}ms` : ""}`); }
    catch (error) { setMessage(errorText(error)); }
    finally { setBusy(""); }
  }

  async function createProvider(body: Record<string, unknown>) {
    setBusy("provider-save"); setMessage("");
    try { const created = await systemApi.createLlmProvider(body); setProviders((items) => [...items, created]); setProviderEditor(false); setMessage("Provider 已创建；仅保存 Secret 引用，不保存密钥值"); }
    catch (error) { setMessage(errorText(error)); }
    finally { setBusy(""); }
  }

  async function updateProvider(provider: LlmProvider, body: Record<string, unknown>) {
    setBusy("provider-save"); setMessage("");
    try { const updated = await systemApi.updateLlmProvider(provider.provider_id, body); setProviders((items) => items.map((item) => item.provider_id === updated.provider_id ? updated : item)); setEditingProvider(null); setMessage("Provider 已更新；端点与 Secret 引用保持不变"); }
    catch (error) { setMessage(errorText(error)); }
    finally { setBusy(""); }
  }

  async function createDraft(body: Record<string, unknown>) {
    setBusy("draft-create"); setMessage("");
    try { const created = await systemApi.createLlmDraft(body); setVersions((items) => [created, ...items]); setSelectedId(created.version_id); setDraftEditor(false); setMessage("草稿已创建，当前运行版本未改变"); }
    catch (error) { setMessage(errorText(error)); }
    finally { setBusy(""); }
  }

  return <section className="llmPage">
    <header className="pageHeading"><div><h1>LLM 治理</h1><p>管理 Provider 引用、组织级路由、运行参数、用量成本与受审计版本。</p></div></header>
    <div className="llmTabs" role="tablist" aria-label="LLM 治理功能">
      {tabs.map(([key, label], index) => <button id={`llm-tab-${key}`} tabIndex={tab === key ? 0 : -1} key={key} role="tab" aria-selected={tab === key} onKeyDown={(event) => moveTab(event, index)} onClick={() => setTab(key)}>{label}</button>)}
    </div>
    {message ? <div className="llmNotice" role="status">{message}</div> : null}
    {tab === "config" ? <ConfigurationTab canWrite={canWrite} canTest={canTest} providers={providers} organizationId={organizationId} setOrganizationId={setOrganizationId} loadVersions={loadVersions} busy={busy} selected={selected} routes={routes} patchRoute={patchRoute} dirty={dirty} saveRoutes={saveRoutes} validateDraft={validateDraft} connectionTest={connectionTest} providerEditor={providerEditor} setProviderEditor={setProviderEditor} createProvider={createProvider} editingProvider={editingProvider} setEditingProvider={setEditingProvider} updateProvider={updateProvider} draftEditor={draftEditor} setDraftEditor={setDraftEditor} createDraft={createDraft} /> : null}
    {tab === "usage" ? <UsageTab usageState={usageState} points={points} breakdown={breakdown} scenarioBreakdown={scenarioBreakdown} failureBreakdown={failureBreakdown} invocations={invocations} filters={filters} setFilters={setFilters} onLoad={loadUsage} onLoadMore={loadMoreInvocations} hasMore={(usageState.kind === "success" || usageState.kind === "empty") && invocationPage.has_more} loading={busy === "usage"} /> : null}
    {tab === "versions" ? <VersionsTab organizationId={organizationId} setOrganizationId={setOrganizationId} loadVersions={loadVersions} loadMore={loadMoreVersions} hasMore={versionPage.has_more} versions={versions} loading={busy === "versions"} /> : null}
    {tab === "audit" ? <AuditTab data={audit} onPageChange={(page) => void loadAuditPage(page)} /> : null}
  </section>;
}

function ConfigurationTab(props: { canWrite: boolean; canTest: boolean; providers: LlmProvider[]; organizationId: string; setOrganizationId: (v: string) => void; loadVersions: () => void; busy: string; selected?: LlmVersion; routes: LlmRoute[]; patchRoute: (i: number, patch: Partial<LlmRoute>) => void; dirty: boolean; saveRoutes: () => void; validateDraft: () => void; connectionTest: (provider: LlmProvider) => void; providerEditor: boolean; setProviderEditor: (open: boolean) => void; createProvider: (body: Record<string, unknown>) => void; editingProvider: LlmProvider | null; setEditingProvider: (provider: LlmProvider | null) => void; updateProvider: (provider: LlmProvider, body: Record<string, unknown>) => void; draftEditor: boolean; setDraftEditor: (open: boolean) => void; createDraft: (body: Record<string, unknown>) => void }) {
  return <div role="tabpanel" className="llmConfigGrid">
    <section className="llmPanel providerPanel"><div className="panelTitleRow"><div><h2>Provider 连接</h2><p className="panelHelp">只显示 Kubernetes Secret 引用名和 key，不读取或编辑密钥值。</p></div>{props.canWrite ? <button onClick={() => props.setProviderEditor(true)}>新增 Provider</button> : null}</div>
      {props.providers.length ? <div className="tableScroll"><table><thead><tr><th>名称</th><th>类型 / Base URL</th><th>Secret 引用</th><th>状态</th><th>操作</th></tr></thead><tbody>{props.providers.map((provider) => <tr key={provider.provider_id}><td><strong>{provider.name}</strong></td><td>{provider.provider_type}<br />{provider.base_url}</td><td><code>{provider.secret_ref.namespace}/{provider.secret_ref.name}:{provider.secret_ref.key}</code></td><td>{provider.enabled ? "启用" : "停用"}<br />{provider.last_connection_test_status || "未测试"}</td><td><div className="providerActions">{props.canWrite ? <button aria-label={`编辑 ${provider.name}`} onClick={() => props.setEditingProvider(provider)}>编辑</button> : null}{props.canTest ? <button disabled={props.busy === `test-${provider.provider_id}`} onClick={() => props.connectionTest(provider)}>{props.busy === `test-${provider.provider_id}` ? "测试中…" : "测试连接"}</button> : null}</div></td></tr>)}</tbody></table></div> : <p className="structuredEmpty">服务端未返回 Provider 配置。</p>}
      {props.providerEditor ? <ProviderEditor busy={props.busy === "provider-save"} onCancel={() => props.setProviderEditor(false)} onSave={props.createProvider} /> : null}
      {props.editingProvider ? <ProviderEdit provider={props.editingProvider} busy={props.busy === "provider-save"} onCancel={() => props.setEditingProvider(null)} onSave={(body) => props.updateProvider(props.editingProvider as LlmProvider, body)} /> : null}
    </section>
    <div className="organizationLoader"><label>组织 ID<input value={props.organizationId} onChange={(e) => props.setOrganizationId(e.target.value)} /></label><div className="providerActions">{props.canWrite ? <button disabled={!props.organizationId.trim()} onClick={() => props.setDraftEditor(true)}>创建草稿</button> : null}<button onClick={props.loadVersions}>加载组织配置</button></div></div>
    {props.draftEditor ? <DraftEditor organizationId={props.organizationId.trim()} busy={props.busy === "draft-create"} onCancel={() => props.setDraftEditor(false)} onSave={props.createDraft} /> : null}
    <section className="llmPanel"><h2>场景模型路由</h2><p className="panelHelp">主模型与可选降级模型按业务场景独立配置。</p>
      {props.routes.length ? props.routes.map((route, index) => <div className="routeRow" key={route.scenario}><strong>{route.scenario}</strong><label>主模型<input className="monoField" value={route.primary_model} onChange={(e) => props.patchRoute(index, { primary_model: e.target.value })} disabled={props.selected?.status !== "draft"} /></label><label>降级模型<input className="monoField" value={route.fallback_model || ""} onChange={(e) => props.patchRoute(index, { fallback_model: e.target.value || null })} disabled={props.selected?.status !== "draft"} /></label></div>) : <p className="structuredEmpty">加载组织后显示服务端配置的场景路由。</p>}
    </section>
    <section className="llmPanel"><h2>运行参数</h2><p className="panelHelp">参数边界：温度 0–2、超时 1–300 秒、重试 0–20 次。</p>
      {props.routes.length ? props.routes.map((route, index) => <fieldset className="runtimeFields" key={route.scenario}><legend>{route.scenario}</legend><label>Temperature<input type="number" min="0" max="2" step="0.1" value={route.temperature} onChange={(e) => props.patchRoute(index, { temperature: Number(e.target.value) })} /></label><label>最大输出 Token<input type="number" min="1" max="1000000" value={route.max_output_tokens} onChange={(e) => props.patchRoute(index, { max_output_tokens: Number(e.target.value) })} /></label><label>超时（秒）<input type="number" min="1" max="300" value={route.timeout_seconds} onChange={(e) => props.patchRoute(index, { timeout_seconds: Number(e.target.value) })} /></label><label>重试次数<input type="number" min="0" max="20" value={route.max_retries} onChange={(e) => props.patchRoute(index, { max_retries: Number(e.target.value) })} /></label><label>熔断阈值<input type="number" min="1" max="10000" value={route.circuit_breaker_threshold} onChange={(e) => props.patchRoute(index, { circuit_breaker_threshold: Number(e.target.value) })} /></label><label>恢复探测（秒）<input type="number" min="1" max="86400" value={route.recovery_probe_seconds} onChange={(e) => props.patchRoute(index, { recovery_probe_seconds: Number(e.target.value) })} /></label></fieldset>) : <p className="structuredEmpty">加载草稿后编辑真实运行参数。</p>}
      <div className="panelActions"><span>{props.selected ? `版本 ${props.selected.version_number} · ${props.selected.status} · revision ${props.selected.revision}` : "未加载草稿"}</span>{props.canWrite ? <><button disabled={props.selected?.status !== "draft" || props.dirty || props.busy === "validate"} onClick={props.validateDraft}>验证草稿</button><button className="primaryAction" disabled={!props.dirty || props.selected?.status !== "draft" || props.busy === "save"} onClick={props.saveRoutes}>保存草稿</button></> : null}</div>
    </section>
  </div>;
}

function ProviderEditor({ busy, onCancel, onSave }: { busy: boolean; onCancel: () => void; onSave: (body: Record<string, unknown>) => void }) {
  const [form, setForm] = React.useState({ name: "", provider_type: "openai", base_url: "", namespace: "", secret_name: "", secret_key: "", reason: "", idempotency_key: "" });
  const set = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const valid = form.name.trim() && /^https:\/\//.test(form.base_url) && form.namespace.trim() && form.secret_name.trim() && form.secret_key.trim() && form.reason.trim() && form.idempotency_key.trim();
  return <div className="providerEditor" role="group" aria-label="新增 Provider 表单"><label>Provider 名称<input value={form.name} onChange={(e) => set("name", e.target.value)} /></label><label>Provider 类型<select value={form.provider_type} onChange={(e) => set("provider_type", e.target.value)}><option value="openai">OpenAI</option><option value="openai_compatible">OpenAI Compatible</option><option value="anthropic">Anthropic</option><option value="azure_openai">Azure OpenAI</option></select></label><label>Base URL<input value={form.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder="https://" /></label><label>Secret namespace<input className="monoField" value={form.namespace} onChange={(e) => set("namespace", e.target.value)} /></label><label>Secret name<input className="monoField" value={form.secret_name} onChange={(e) => set("secret_name", e.target.value)} /></label><label>Secret key<input className="monoField" value={form.secret_key} onChange={(e) => set("secret_key", e.target.value)} /></label><label>变更原因<input value={form.reason} onChange={(e) => set("reason", e.target.value)} /></label><label>创建幂等键<input className="monoField" value={form.idempotency_key} onChange={(e) => set("idempotency_key", e.target.value)} /></label><div className="panelActions"><button onClick={onCancel}>取消</button><button className="primaryAction" disabled={!valid || busy} onClick={() => onSave({ name: form.name.trim(), provider_type: form.provider_type, base_url: form.base_url.trim(), secret_ref: { namespace: form.namespace.trim(), name: form.secret_name.trim(), key: form.secret_key.trim() }, enabled: true, reason: form.reason.trim(), idempotency_key: form.idempotency_key.trim() })}>保存 Provider</button></div></div>;
}

function ProviderEdit({ provider, busy, onCancel, onSave }: { provider: LlmProvider; busy: boolean; onCancel: () => void; onSave: (body: Record<string, unknown>) => void }) {
  const [name, setName] = React.useState(provider.name); const [enabled, setEnabled] = React.useState(provider.enabled); const [reason, setReason] = React.useState(""); const [key, setKey] = React.useState("");
  return <div className="providerEditor" role="group" aria-label="编辑 Provider 表单"><label>编辑 Provider 名称<input value={name} onChange={(e) => setName(e.target.value)} /></label><label>启用状态<select value={String(enabled)} onChange={(e) => setEnabled(e.target.value === "true")}><option value="true">启用</option><option value="false">停用</option></select></label><label>编辑原因<input value={reason} onChange={(e) => setReason(e.target.value)} /></label><label>编辑幂等键<input className="monoField" value={key} onChange={(e) => setKey(e.target.value)} /></label><p className="panelHelp">Base URL 与 Secret 引用按契约不可原地替换。</p><div className="panelActions"><button onClick={onCancel}>取消</button><button className="primaryAction" disabled={!name.trim() || !reason.trim() || !key.trim() || busy} onClick={() => onSave({ expected_revision: provider.revision, name: name.trim(), enabled, reason: reason.trim(), idempotency_key: key.trim() })}>保存 Provider 修改</button></div></div>;
}

function DraftEditor({ organizationId, busy, onCancel, onSave }: { organizationId: string; busy: boolean; onCancel: () => void; onSave: (body: Record<string, unknown>) => void }) {
  const [description, setDescription] = React.useState(""); const [reason, setReason] = React.useState(""); const [key, setKey] = React.useState("");
  return <section className="llmPanel"><h2>创建组织配置草稿</h2><div className="providerEditor"><label>草稿说明<input value={description} onChange={(e) => setDescription(e.target.value)} /></label><label>草稿原因<input value={reason} onChange={(e) => setReason(e.target.value)} /></label><label>草稿幂等键<input className="monoField" value={key} onChange={(e) => setKey(e.target.value)} /></label><div className="panelActions"><button onClick={onCancel}>取消</button><button className="primaryAction" disabled={!organizationId || !reason.trim() || !key.trim() || busy} onClick={() => onSave({ organization_id: organizationId, description: description.trim() || null, reason: reason.trim(), idempotency_key: key.trim() })}>确认创建草稿</button></div></div></section>;
}

function UsageTab({ usageState, points, breakdown, scenarioBreakdown, failureBreakdown, invocations, filters, setFilters, onLoad, onLoadMore, hasMore, loading }: { usageState: UsageState; points: LlmUsagePoint[]; breakdown: LlmBreakdown[]; scenarioBreakdown: LlmBreakdown[]; failureBreakdown: LlmBreakdown[]; invocations: LlmInvocation[]; filters: LlmUsageFilters; setFilters: React.Dispatch<React.SetStateAction<LlmUsageFilters>>; onLoad: () => void; onLoadMore: () => void; hasMore: boolean; loading: boolean }) {
  const update = (key: keyof LlmUsageFilters, value: string) => setFilters((current) => ({ ...current, [key]: value || undefined }));
  const usage = usageState.kind === "empty" || usageState.kind === "success" ? usageState.data : null;
  return <div role="tabpanel" className="usageWorkspace"><div className="usageFilters"><label>开始时间<input type="datetime-local" onChange={(e) => update("start_at", e.target.value ? new Date(e.target.value).toISOString() : "")} /></label><label>结束时间<input type="datetime-local" onChange={(e) => update("end_at", e.target.value ? new Date(e.target.value).toISOString() : "")} /></label><label>Provider ID<input className="monoField" onChange={(e) => update("provider_config_id", e.target.value)} /></label><label>模型<input className="monoField" onChange={(e) => update("model", e.target.value)} /></label><label>场景<input onChange={(e) => update("scenario", e.target.value)} /></label><label>组织<input onChange={(e) => update("organization_id", e.target.value)} /></label><label>店铺<input onChange={(e) => update("store_id", e.target.value)} /></label><button onClick={onLoad} disabled={loading}>{loading ? "查询中…" : "查询用量"}</button></div>
    {usageState.kind === "loading" ? <div className="structuredEmpty">正在加载用量与成本数据</div> : null}
    {usageState.kind === "error" ? <div className="structuredEmpty">{usageState.message}</div> : null}
    {usage ? <><div className="usageCards"><article><span>总请求数</span><strong>{usage.calls}</strong></article><article><span>总 Token</span><strong>{usage.total_tokens}</strong></article><article><span>输入 Token</span><strong>{usage.input_tokens}</strong></article><article><span>输出 Token</span><strong>{usage.output_tokens}</strong></article><article><span>P95 延迟</span><strong>{usage.p95_latency_ms === null ? "—" : `${usage.p95_latency_ms} ms`}</strong></article><article><span>错误率</span><strong>{usage.error_rate === null ? "—" : `${(usage.error_rate * 100).toFixed(2)}%`}</strong></article><article><span>降级率</span><strong>{usage.fallback_rate === null ? "—" : `${(usage.fallback_rate * 100).toFixed(2)}%`}</strong></article><article><span>估算成本</span><strong>{usage.estimated_cost_micros === null ? Object.entries(usage.cost_by_currency).map(([currency, amount]) => <span key={currency}>{money(amount, currency)}</span>) : money(usage.estimated_cost_micros, Object.keys(usage.cost_by_currency)[0] || "USD")}</strong></article></div>{usageState.kind === "empty" ? <div className="structuredEmpty">当前筛选范围内暂无模型调用</div> : null}</> : null}
    {points.length ? <section className="llmPanel" data-testid="usage-chart"><h2>用量时序</h2><div className="timeseriesBars">{points.map((point) => <div key={`${point.bucket}-${point.currency}`}><span>{new Date(point.bucket).toLocaleString()}</span><meter min="0" max={Math.max(...points.map((p) => p.calls), 1)} value={point.calls} /><strong>{point.calls} 次</strong></div>)}</div></section> : null}
    <section className="llmPanel"><h2>模型成本分布</h2>{breakdown.length ? <table><thead><tr><th>模型</th><th>调用</th><th>Token</th><th>估算成本</th></tr></thead><tbody>{breakdown.map((item) => <tr key={`${item.key}-${item.currency}`}><td><code>{item.key}</code></td><td>{item.calls}</td><td>{item.total_tokens}</td><td>{money(item.estimated_cost_micros, item.currency)}</td></tr>)}</tbody></table> : <p className="structuredEmpty">暂无模型或场景分布。</p>}</section>
    <BreakdownPanel title="场景用量分布" label="场景" items={scenarioBreakdown} />
    <BreakdownPanel title="失败原因分布" label="错误码" items={failureBreakdown} />
    <section className="llmPanel"><h2>调用明细</h2>{invocations.length ? <div className="tableScroll"><table><thead><tr><th>调用 / 时间</th><th>Provider</th><th>组织 / 店铺</th><th>模型 / 场景</th><th>路由 / 延迟</th><th>Token / 成本</th><th>状态 / 失败原因</th></tr></thead><tbody>{invocations.map((item) => <tr key={item.invocation_id}><td><span>{item.invocation_id}</span><br />{new Date(item.occurred_at).toLocaleString()}</td><td><span>{item.provider_name}</span><br /><span>{item.provider_config_id}</span></td><td>{item.organization_id}<br />{item.store_id || "—"}</td><td><code>{item.model}</code><br /><span>{item.scenario}</span></td><td><span>{item.route_role}</span><br /><span>调用延迟：{item.latency_ms} ms</span></td><td><span>输入 {item.input_tokens}</span><br /><span>输出 {item.output_tokens}</span><br /><span>成本：{money(item.estimated_cost_micros, item.currency)}</span></td><td>{item.status}<br /><span>{item.error_code || "—"}</span></td></tr>)}</tbody></table></div> : <p className="structuredEmpty">暂无脱敏调用明细。</p>}{hasMore ? <button onClick={onLoadMore}>加载更多调用</button> : null}</section>
  </div>;
}

function BreakdownPanel({ title, label, items }: { title: string; label: string; items: LlmBreakdown[] }) { return <section className="llmPanel"><h2>{title}</h2>{items.length ? <div className="tableScroll"><table><thead><tr><th>{label}</th><th>调用</th><th>Token</th><th>估算成本</th></tr></thead><tbody>{items.map((item) => <tr key={`${item.key}-${item.currency}`}><td><code>{item.key || "未标记"}</code></td><td>{item.calls}</td><td>{item.total_tokens}</td><td>{money(item.estimated_cost_micros, item.currency)}</td></tr>)}</tbody></table></div> : <p className="structuredEmpty">当前筛选范围内暂无{title}。</p>}</section>; }

function VersionsTab({ organizationId, setOrganizationId, loadVersions, loadMore, hasMore, versions, loading }: { organizationId: string; setOrganizationId: (v: string) => void; loadVersions: () => void; loadMore: () => void; hasMore: boolean; versions: LlmVersion[]; loading: boolean }) {
  return <div role="tabpanel"><div className="organizationLoader"><label>组织 ID<input value={organizationId} onChange={(e) => setOrganizationId(e.target.value)} /></label><button onClick={loadVersions}>{loading ? "加载中…" : "查询版本"}</button></div><section className="llmPanel"><h2>真实配置版本</h2>{versions.length ? <div className="tableScroll"><table><thead><tr><th>版本</th><th>状态 / revision</th><th>创建者 / 时间</th><th>发布者 / 时间</th><th>评测</th></tr></thead><tbody>{versions.map((item) => <tr key={item.version_id}><td>版本 {item.version_number}<br /><span>{item.version_id}</span></td><td>{item.status}<br />revision {item.revision}</td><td>{item.created_by_system_admin_user_id}<br />{new Date(item.created_at).toLocaleString()}</td><td>{item.published_by_system_admin_user_id || "未发布"}<br />{item.published_at ? new Date(item.published_at).toLocaleString() : "—"}</td><td>{item.evaluation?.evaluation_run_id || "未绑定评测"}</td></tr>)}</tbody></table></div> : <p className="structuredEmpty">输入组织 ID 后查询不可变版本历史。</p>}{hasMore ? <button onClick={loadMore}>加载更多版本</button> : null}</section></div>;
}

function AuditTab({ data, onPageChange }: { data: { items: JsonRecord[]; page: { page: number; page_size: number; total: number } }; onPageChange: (page: number) => void }) { return <div role="tabpanel"><section className="llmPanel"><h2>LLM 变更审计</h2><p className="panelHelp">仅展示操作者、动作、原因、安全结果摘要和时间；不展示 Prompt、消息正文或密钥。</p>{data.items.length ? <div className="tableScroll"><table><thead><tr><th>操作者</th><th>动作</th><th>原因</th><th>结果</th><th>时间</th></tr></thead><tbody>{data.items.map((item, index) => { const diff = item.diff_summary && typeof item.diff_summary === "object" ? item.diff_summary as JsonRecord : {}; const snapshot = diff.response_snapshot && typeof diff.response_snapshot === "object" ? diff.response_snapshot as JsonRecord : {}; const result = diff.result || diff.status || snapshot.status || "—"; return <tr key={String(item.audit_log_id || index)}><td>{String(item.actor_system_user_id || "—")}</td><td>{String(item.action || "—")}</td><td>{String(item.reason || "—")}</td><td>{String(result)}</td><td>{item.created_at ? new Date(String(item.created_at)).toLocaleString() : "—"}</td></tr>; })}</tbody></table></div> : <p className="structuredEmpty">服务端未返回 LLM 相关审计记录。</p>}<PaginationControls page={data.page} onPageChange={onPageChange} /></section></div>; }
