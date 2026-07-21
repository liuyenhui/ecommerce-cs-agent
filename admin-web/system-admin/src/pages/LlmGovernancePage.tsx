import React from "react";
import { systemApi } from "../system-api";
import type { LlmModel, LangGraphLlmBindings, LlmRoute } from "../system-types";

const WRITE_ROLES = new Set(["super_admin", "release_admin"]);
const TEST_ROLES = new Set(["super_admin", "release_admin", "technical_support"]);
const emptyForm = { name: "", provider: "openai_compatible", base_url: "", model_id: "", api_key: "" };
const errorText = (error: unknown) => error instanceof Error && error.message.startsWith("409 ") ? "配置存在引用或已被其他管理员更新，请先解除绑定并重新加载" : error instanceof Error ? error.message : String(error);
const canonical = (value: Record<string, string>) => JSON.stringify(Object.entries(value).filter(([, id]) => id).sort(([a], [b]) => a.localeCompare(b)));

export function validateLlmRoute(_route: LlmRoute): string | null { return null; }

export function LlmGovernancePage({ roles = ["super_admin"] }: { roles?: string[] }) {
  const initialTab = /(?:^|[?&])tab=langgraph(?:&|$)/.test(window.location.search) ? "langgraph" : "llms";
  const [tab, setTabState] = React.useState<"llms" | "langgraph">(initialTab);
  const [models, setModels] = React.useState<LlmModel[]>([]);
  const [bindings, setBindings] = React.useState<LangGraphLlmBindings | null>(null);
  const [bindingSnapshot, setBindingSnapshot] = React.useState("{}");
  const [selected, setSelected] = React.useState<Record<string, string>>({});
  const [form, setForm] = React.useState(emptyForm);
  const [editing, setEditing] = React.useState<LlmModel | null>(null);
  const [showForm, setShowForm] = React.useState(false);
  const [deleting, setDeleting] = React.useState<LlmModel | null>(null);
  const [busy, setBusy] = React.useState("");
  const [message, setMessage] = React.useState("");
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);
  const firstInputRef = React.useRef<HTMLInputElement | null>(null);
  const canWrite = roles.some((role) => WRITE_ROLES.has(role));
  const canTest = roles.some((role) => TEST_ROLES.has(role));

  const load = React.useCallback(async (signal?: AbortSignal) => {
    const [llmData, bindingData] = await Promise.all([systemApi.llms(signal), systemApi.langGraphLlmBindings(signal)]);
    const current = Object.fromEntries(bindingData.nodes.filter((node) => node.llm_id).map((node) => [node.node_id, String(node.llm_id)]));
    setModels(llmData.items); setBindings(bindingData); setSelected(current); setBindingSnapshot(canonical(current));
  }, []);

  React.useEffect(() => { const controller = new AbortController(); load(controller.signal).catch((error) => { if (!controller.signal.aborted) setMessage(errorText(error)); }); return () => controller.abort(); }, [load]);
  React.useEffect(() => { if (showForm) firstInputRef.current?.focus(); }, [showForm]);

  function setTab(next: "llms" | "langgraph") {
    const url = new URL(window.location.href); url.searchParams.set("tab", next); window.history.replaceState({}, "", url);
    setTabState(next);
  }
  function closeForm() { if (busy === "model") return; setShowForm(false); setEditing(null); setForm(emptyForm); requestAnimationFrame(() => triggerRef.current?.focus()); }
  function openCreate(event: React.MouseEvent<HTMLButtonElement>) { triggerRef.current = event.currentTarget; setEditing(null); setForm(emptyForm); setShowForm(true); }
  function openEdit(model: LlmModel, event: React.MouseEvent<HTMLButtonElement>) { triggerRef.current = event.currentTarget; setEditing(model); setForm({ name: model.name, provider: model.provider, base_url: model.base_url, model_id: model.model_id, api_key: "" }); setShowForm(true); }

  async function saveModel() {
    if (!form.name.trim() || !form.base_url.trim() || !form.model_id.trim() || (!editing && !form.api_key)) return;
    setBusy("model"); setMessage("");
    try {
      const body = { ...form, name: form.name.trim(), base_url: form.base_url.trim(), model_id: form.model_id.trim() };
      if (editing) await systemApi.updateLlm(editing.llm_id, { expected_revision: editing.revision, name: body.name, provider: body.provider, base_url: body.base_url, model_id: body.model_id, ...(body.api_key ? { api_key: body.api_key } : {}) });
      else await systemApi.createLlm(body);
      setShowForm(false); setEditing(null); setForm(emptyForm); await load(); setMessage(editing ? "LLM 已更新；连接信息变化后请重新测试" : "LLM 已添加，请测试连接后再绑定节点");
    } catch (error) { setMessage(errorText(error)); }
    finally { setBusy(""); }
  }
  async function testConnection(model: LlmModel) { setBusy(`test-${model.llm_id}`); setMessage("连接测试进行中…"); try { const result = await systemApi.testLlm(model.llm_id); await load(); setMessage(result.status === "passed" ? "连接测试通过" : `连接测试失败：${result.error_code || "connection_failed"}`); } catch (error) { setMessage(errorText(error)); } finally { setBusy(""); } }
  async function toggleModel(model: LlmModel) { setBusy(`toggle-${model.llm_id}`); try { await systemApi.updateLlm(model.llm_id, { expected_revision: model.revision, enabled: !model.enabled }); await load(); } catch (error) { setMessage(errorText(error)); } finally { setBusy(""); } }
  async function deleteModel() { if (!deleting) return; setBusy(`delete-${deleting.llm_id}`); try { await systemApi.deleteLlm(deleting.llm_id); setDeleting(null); await load(); setMessage("LLM 已删除"); } catch (error) { setMessage(errorText(error)); setDeleting(null); } finally { setBusy(""); } }
  async function saveBindings() {
    if (!bindings || canonical(selected) === bindingSnapshot) return;
    const required = bindings.nodes.filter((node) => node.uses_llm && node.required);
    if (required.some((node) => !selected[node.node_id])) { setMessage("必需节点必须选择 LLM"); return; }
    setBusy("bindings");
    try {
      const updated = await systemApi.replaceLangGraphLlmBindings({ expected_revision: bindings.revision, bindings: bindings.nodes.filter((node) => node.uses_llm).map((node) => ({ node_id: node.node_id, llm_id: selected[node.node_id] })) });
      const current = Object.fromEntries(updated.nodes.filter((node) => node.llm_id).map((node) => [node.node_id, String(node.llm_id)]));
      setBindings(updated); setSelected(current); setBindingSnapshot(canonical(current)); setMessage("节点绑定已保存，新请求立即生效");
    } catch (error) { setMessage(errorText(error)); } finally { setBusy(""); }
  }

  const bindable = models.filter((model) => model.enabled && model.last_connection_test_status === "passed");
  const bindingDirty = canonical(selected) !== bindingSnapshot;
  return <section className="llmPage">
    <header className="pageHeading"><div><h1>LLM 配置</h1><p>添加可用模型，并为真实 LangGraph 节点选择运行模型。</p></div></header>
    <div className="configTabs" role="tablist" aria-label="LLM 配置分类"><button role="tab" aria-selected={tab === "llms"} aria-controls="llms-panel" onClick={() => setTab("llms")}>LLM</button><button role="tab" aria-selected={tab === "langgraph"} aria-controls="langgraph-panel" onClick={() => setTab("langgraph")}>LangGraph</button></div>
    {message ? <div className="inlineNotice" role="status">{message}</div> : null}

    <section id="llms-panel" role="tabpanel" hidden={tab !== "llms"} className="panel llmConfigSection" aria-labelledby="available-llms-title">
      <div className="sectionHeader"><h2 id="available-llms-title">可用 LLM <small className="sectionTitleNote">（API Key 仅通过 HTTPS 提交一次，之后只显示掩码）</small></h2>{canWrite ? <button className="primaryAction" onClick={openCreate}>添加 LLM</button> : null}</div>
      {models.length ? <div className="tableScroll"><table><thead><tr><th>名称</th><th>厂商 / 模型</th><th>Base URL</th><th>API Key</th><th>状态</th><th>操作</th></tr></thead><tbody>{models.map((model) => <tr key={model.llm_id}><td data-label="名称"><strong>{model.name}</strong></td><td data-label="厂商 / 模型">{model.provider}<br /><span className="monoField">{model.model_id}</span></td><td data-label="Base URL">{model.base_url}</td><td data-label="API Key"><span className="secretRef">{model.api_key_masked}</span></td><td data-label="状态">{model.enabled ? model.status : "已停用"}<br />{model.last_connection_test_status || "未测试"}</td><td data-label="操作"><div className="providerActions">{canWrite ? <button onClick={(event) => openEdit(model, event)}>编辑 / 换 Key</button> : null}{canTest ? <button disabled={busy === `test-${model.llm_id}`} onClick={() => void testConnection(model)}>测试连接</button> : null}{canWrite ? <button disabled={Boolean(busy)} onClick={() => void toggleModel(model)}>{model.enabled ? "停用" : "启用"}</button> : null}{canWrite ? <button className="dangerAction" disabled={Boolean(busy)} onClick={() => setDeleting(model)}>删除</button> : null}</div></td></tr>)}</tbody></table></div> : <p className="structuredEmpty">尚未添加 LLM。</p>}
    </section>

    <section id="langgraph-panel" role="tabpanel" hidden={tab !== "langgraph"} className="panel llmConfigSection" aria-labelledby="node-bindings-title">
      <div className="sectionHeader"><h2 id="node-bindings-title">LangGraph 节点使用的 LLM <small className="sectionTitleNote">（全系统配置，保存后立即作用于新请求）</small></h2></div>
      {bindings ? <div className="nodeBindingList">{bindings.nodes.map((node) => <div className="nodeBindingRow" key={node.node_id}><div><strong>{node.node_id}</strong><span>{node.label}</span><small>{node.description}</small></div>{node.uses_llm ? <label><span className="srOnly">{node.label} 使用的 LLM</span><select disabled={!canWrite || busy === "bindings"} value={selected[node.node_id] || ""} onChange={(event) => setSelected({ ...selected, [node.node_id]: event.target.value })}><option value="">请选择 LLM</option>{bindable.map((model) => <option key={model.llm_id} value={model.llm_id}>{model.name} · {model.model_id}</option>)}</select></label> : <span className="statusBadge">不使用 LLM</span>}</div>)}</div> : <p className="structuredEmpty">正在读取节点注册表…</p>}
      {canWrite ? <div className="panelActions"><button className="primaryAction" aria-busy={busy === "bindings"} disabled={!bindings || !bindingDirty || busy === "bindings"} onClick={() => void saveBindings()}>{busy === "bindings" ? "保存中…" : "保存全部绑定"}</button></div> : null}
    </section>

    {showForm ? <div className="modalBackdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeForm(); }}><div className="configModal" role="dialog" aria-modal="true" aria-label={editing ? "编辑 LLM 表单" : "添加 LLM 表单"} onKeyDown={(event) => { if (event.key === "Escape") closeForm(); }}><h2>{editing ? "编辑 LLM" : "添加 LLM"}</h2><div className="providerEditor"><label>名称<input ref={firstInputRef} name="name" autoComplete="off" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label>厂商<select name="provider" value={form.provider} onChange={(event) => setForm({ ...form, provider: event.target.value })}><option value="openai">OpenAI</option><option value="deepseek">DeepSeek</option><option value="qwen">通义千问</option><option value="openai_compatible">OpenAI 兼容</option></select></label><label>Base URL<input name="base_url" autoComplete="off" value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} /></label><label>模型 ID<input name="model_id" autoComplete="off" value={form.model_id} onChange={(event) => setForm({ ...form, model_id: event.target.value })} /></label>{editing ? <p className="maskedKeyValue">当前 API Key：<strong>{editing.api_key_masked}</strong></p> : null}<label>API Key{editing ? "（输入新值才会更换）" : ""}<input name="api_key" type="password" autoComplete="new-password" value={form.api_key} placeholder={editing ? "输入新 Key" : ""} onChange={(event) => setForm({ ...form, api_key: event.target.value })} /></label></div><div className="panelActions"><button disabled={busy === "model"} onClick={closeForm}>取消</button><button className="primaryAction" disabled={busy === "model"} onClick={() => void saveModel()}>{busy === "model" ? "保存中…" : "保存 LLM"}</button></div></div></div> : null}
    {deleting ? <div className="modalBackdrop"><div className="configModal compactModal" role="alertdialog" aria-modal="true" aria-labelledby="delete-llm-title"><h2 id="delete-llm-title">删除 {deleting.name}？</h2><p>删除后无法恢复；如存在 LangGraph 绑定或历史引用，系统会阻止删除并提示先解除绑定或停用。</p><div className="panelActions"><button disabled={busy.startsWith("delete-")} onClick={() => setDeleting(null)}>取消</button><button className="dangerAction" disabled={busy.startsWith("delete-")} onClick={() => void deleteModel()}>{busy.startsWith("delete-") ? "删除中…" : "确认删除"}</button></div></div></div> : null}
  </section>;
}
