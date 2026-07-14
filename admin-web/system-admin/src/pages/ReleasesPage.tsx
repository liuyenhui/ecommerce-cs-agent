import React from "react";
import { systemApi } from "../system-api";
import type { LlmVersion } from "../system-types";

const failure = (error: unknown) => error instanceof Error && error.message.startsWith("409 ") ? "配置已被其他管理员更新，请重新加载" : (error instanceof Error ? error.message : String(error));

export function ReleasesPage() {
  const [organizationId, setOrganizationId] = React.useState("");
  const [versions, setVersions] = React.useState<LlmVersion[]>([]);
  const [selected, setSelected] = React.useState<LlmVersion | null>(null);
  const [mode, setMode] = React.useState<"submit" | "publish">("publish");
  const [evaluationId, setEvaluationId] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [key, setKey] = React.useState("");
  const [message, setMessage] = React.useState("");
  const controller = React.useRef<AbortController | null>(null);
  React.useEffect(() => () => controller.current?.abort(), []);

  async function load() {
    if (!organizationId.trim()) { setMessage("请输入组织 ID"); return; }
    controller.current?.abort(); const next = new AbortController(); controller.current = next;
    try { const data = await systemApi.llmVersions(organizationId.trim(), undefined, next.signal); setVersions(data.items); setMessage(""); }
    catch (error) { if (!next.signal.aborted) setMessage(failure(error)); }
  }

  async function publish() {
    if (!selected || !reason.trim() || !key.trim()) { setMessage("发布原因和幂等键不能为空"); return; }
    if (!window.confirm(`确认发布版本 ${selected.version_number}？该操作会切换运行流量。`)) return;
    try { const updated = await systemApi.publishLlmVersion(selected.version_id, { expected_revision: selected.revision, reason: reason.trim(), idempotency_key: key.trim() }); setVersions((items) => items.map((item) => item.version_id === updated.version_id ? updated : item)); setSelected(null); setMessage("版本已发布"); }
    catch (error) { setMessage(failure(error)); }
  }

  async function submit() {
    if (!selected || !evaluationId.trim() || !reason.trim() || !key.trim()) { setMessage("评测快照、发布原因和幂等键不能为空"); return; }
    if (!window.confirm(`确认以评测快照 ${evaluationId.trim()} 提交版本 ${selected.version_number}？`)) return;
    try { const updated = await systemApi.submitLlmVersion(selected.version_id, { expected_revision: selected.revision, evaluation_run_id: evaluationId.trim(), reason: reason.trim(), idempotency_key: key.trim() }); setVersions((items) => items.map((item) => item.version_id === updated.version_id ? updated : item)); setSelected(null); setMessage("版本已绑定评测快照并进入待发布状态"); }
    catch (error) { setMessage(failure(error)); }
  }

  async function rollback(version: LlmVersion) {
    const rollbackReason = window.prompt(`请输入回滚到版本 ${version.version_number} 的原因`)?.trim(); if (!rollbackReason) return;
    if (!window.confirm(`确认创建并发布版本 ${version.version_number} 的回滚副本？`)) return;
    try { const updated = await systemApi.rollbackLlmVersion(version.version_id, { reason: rollbackReason, idempotency_key: `rollback-${crypto.randomUUID()}` }); setVersions((items) => [updated, ...items]); setMessage("回滚版本已发布，原版本记录保持不变"); }
    catch (error) { setMessage(failure(error)); }
  }

  return <section className="llmPage"><header className="pageHeading"><div><h1>评测与发布</h1><p>发布只使用真实版本记录及其已绑定评测快照；当前契约不提供独立评测运行列表。</p></div></header>
    <div className="organizationLoader"><label>组织 ID<input value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} /></label><button onClick={load}>查询版本</button></div>
    {message ? <div className="llmNotice" role="status">{message}</div> : null}
    <div className="releaseGrid">
      <section className="llmPanel"><h2>评测运行与门禁</h2>{versions.length ? versions.map((version) => <article className="releaseCard" key={version.version_id}><div><strong>版本 {version.version_number}</strong><span>状态：{version.status}</span><span>评测快照：<code>{version.evaluation?.evaluation_run_id || "未绑定"}</code></span></div>{version.status === "validated" ? <button onClick={() => { setSelected(version); setMode("submit"); setEvaluationId(""); setReason(""); setKey(""); }}>提交版本 {version.version_number}</button> : <span className={version.evaluation ? "gatePassed" : "gateBlocked"}>{version.evaluation ? "已绑定评测快照" : "不可发布：未绑定通过的评测"}</span>}</article>) : <p className="structuredEmpty">输入组织 ID 后展示服务端版本及门禁结果。</p>}</section>
      <section className="llmPanel"><h2>待发布版本</h2>{versions.filter((v) => v.status === "pending_publish").length ? versions.filter((v) => v.status === "pending_publish").map((version) => <article className="releaseCard" key={version.version_id}><div><strong>版本 {version.version_number}</strong><code className="wrapId">{version.version_id}</code><span>评测：{version.evaluation?.evaluation_run_id || "未绑定"}</span></div><button disabled={!version.evaluation} onClick={() => { setSelected(version); setMode("publish"); setReason(""); setKey(""); }}>发布版本 {version.version_number}</button></article>) : <p className="structuredEmpty">暂无通过门禁并等待发布的版本。</p>}</section>
      <section className="llmPanel"><h2>发布记录</h2>{versions.filter((v) => ["running", "superseded", "rolled_back"].includes(v.status)).length ? versions.filter((v) => ["running", "superseded", "rolled_back"].includes(v.status)).map((version) => <article className="releaseCard" key={version.version_id}><div><strong>版本 {version.version_number} · {version.status}</strong><span>{version.published_at ? new Date(version.published_at).toLocaleString() : "发布时间未返回"}</span><span>发布者：{version.published_by_system_admin_user_id || "—"}</span></div><button onClick={() => void rollback(version)}>回滚到此版本</button></article>) : <p className="structuredEmpty">服务端未返回已发布记录。</p>}</section>
    </div>
    {selected ? <div className="releaseDialog" role="dialog" aria-modal="true" aria-labelledby="release-title"><div><h2 id="release-title">{mode === "submit" ? "提交" : "发布"}版本 {selected.version_number}</h2>{mode === "submit" ? <label>评测快照 ID<input className="monoField" value={evaluationId} onChange={(event) => setEvaluationId(event.target.value)} /></label> : <p>评测快照：<code>{selected.evaluation?.evaluation_run_id}</code></p>}<label>发布原因<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label><label>幂等键<input className="monoField" value={key} onChange={(event) => setKey(event.target.value)} /></label><div className="panelActions"><button onClick={() => setSelected(null)}>取消</button><button className="primaryAction" disabled={!reason.trim() || !key.trim() || (mode === "submit" && !evaluationId.trim())} onClick={() => void (mode === "submit" ? submit() : publish())}>{mode === "submit" ? "确认提交" : "确认发布"}</button></div></div></div> : null}
  </section>;
}
