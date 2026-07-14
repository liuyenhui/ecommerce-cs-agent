import React from "react";
import { systemApi } from "../system-api";
import type { LlmReleaseRecord, LlmVersion } from "../system-types";

const failure = (error: unknown) => error instanceof Error && error.message.startsWith("409 ") ? "配置已被其他管理员更新，请重新加载" : (error instanceof Error ? error.message : String(error));
const WRITE_ROLES = new Set(["super_admin", "release_admin"]);

export function ReleasesPage({ roles = ["super_admin"] }: { roles?: string[] }) {
  const canWrite = roles.some((role) => WRITE_ROLES.has(role));
  const [organizationId, setOrganizationId] = React.useState("");
  const [versions, setVersions] = React.useState<LlmVersion[]>([]);
  const [records, setRecords] = React.useState<LlmReleaseRecord[]>([]);
  const [versionCursor, setVersionCursor] = React.useState<string | null>(null); const [releaseCursor, setReleaseCursor] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<LlmVersion | null>(null);
  const [mode, setMode] = React.useState<"submit" | "publish">("publish");
  const [evaluationId, setEvaluationId] = React.useState(""); const [reason, setReason] = React.useState(""); const [key, setKey] = React.useState("");
  const [message, setMessage] = React.useState("");
  const controller = React.useRef<AbortController | null>(null);
  const dialogRef = React.useRef<HTMLDivElement | null>(null);
  const restoreFocus = React.useRef<HTMLElement | null>(null);
  React.useEffect(() => () => controller.current?.abort(), []);

  React.useEffect(() => {
    if (!selected) return;
    const dialog = dialogRef.current; const previous = document.activeElement as HTMLElement | null; restoreFocus.current = previous;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>("button,input,textarea") || []).filter((item) => !item.hasAttribute("disabled"));
    focusable()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setSelected(null); return; }
      if (event.key !== "Tab") return;
      const items = focusable(); if (!items.length) return; const first = items[0]; const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    dialog?.addEventListener("keydown", onKey); return () => { dialog?.removeEventListener("keydown", onKey); restoreFocus.current?.focus(); };
  }, [selected]);

  async function load() {
    if (!organizationId.trim()) { setMessage("请输入组织 ID"); return; }
    controller.current?.abort(); const next = new AbortController(); controller.current = next;
    setVersions([]); setRecords([]); setVersionCursor(null); setReleaseCursor(null); setSelected(null); setMessage("");
    try { const [versionData, releaseData] = await Promise.all([systemApi.llmVersions(organizationId.trim(), undefined, next.signal), systemApi.llmReleaseRecords(organizationId.trim(), undefined, next.signal)]); setVersions(versionData.items); setRecords(releaseData.items); setVersionCursor(versionData.page_info.next_cursor); setReleaseCursor(releaseData.page_info.next_cursor); setMessage(""); }
    catch (error) { if (!next.signal.aborted) setMessage(failure(error)); }
  }
  async function loadMoreVersions() { if (!versionCursor) return; const data = await systemApi.llmVersions(organizationId.trim(), versionCursor); setVersions((items) => [...items, ...data.items]); setVersionCursor(data.page_info.next_cursor); }
  async function loadMoreRecords() { if (!releaseCursor) return; const data = await systemApi.llmReleaseRecords(organizationId.trim(), releaseCursor); setRecords((items) => [...items, ...data.items]); setReleaseCursor(data.page_info.next_cursor); }

  async function publish() {
    if (!selected || !reason.trim() || !key.trim()) { setMessage("发布原因和幂等键不能为空"); return; }
    if (!window.confirm(`确认发布版本 ${selected.version_number}？该操作会切换运行流量。`)) return;
    try { await systemApi.publishLlmVersion(selected.version_id, { expected_revision: selected.revision, reason: reason.trim(), idempotency_key: key.trim() }); setSelected(null); await load(); setMessage("版本已发布，列表已从服务端刷新"); }
    catch (error) { setMessage(failure(error)); }
  }
  async function submit() {
    if (!selected || !evaluationId.trim() || !reason.trim() || !key.trim()) { setMessage("评测快照、发布原因和幂等键不能为空"); return; }
    if (!window.confirm(`确认以评测快照 ${evaluationId.trim()} 提交版本 ${selected.version_number}？`)) return;
    try { await systemApi.submitLlmVersion(selected.version_id, { expected_revision: selected.revision, evaluation_run_id: evaluationId.trim(), reason: reason.trim(), idempotency_key: key.trim() }); setSelected(null); await load(); setMessage("版本已绑定评测快照，列表已从服务端刷新"); }
    catch (error) { setMessage(failure(error)); }
  }
  async function rollback(version: LlmVersion) {
    const rollbackReason = window.prompt(`请输入回滚到版本 ${version.version_number} 的原因`)?.trim(); if (!rollbackReason) return;
    if (!window.confirm(`确认创建并发布版本 ${version.version_number} 的回滚副本？`)) return;
    try { await systemApi.rollbackLlmVersion(version.version_id, { reason: rollbackReason, idempotency_key: `rollback-${crypto.randomUUID()}` }); await load(); setMessage("回滚已完成，版本与发布记录已从服务端刷新"); }
    catch (error) { setMessage(failure(error)); }
  }

  return <section className="llmPage"><header className="pageHeading"><div><h1>评测与发布</h1><p>发布只使用真实版本记录及其已绑定评测快照；当前契约不提供独立评测运行列表。</p></div></header>
    <div className="organizationLoader"><label>组织 ID<input value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} /></label><button onClick={() => void load()}>查询版本</button></div>
    {message ? <div className="llmNotice" role="status">{message}</div> : null}
    <div className="releaseGrid">
      <section className="llmPanel"><h2>评测运行与门禁</h2>{versions.length ? versions.map((version) => <article className="releaseCard" key={version.version_id}><div><strong>版本 {version.version_number}</strong><span>状态：{version.status}</span>{version.status !== "pending_publish" ? <span>评测快照：{version.evaluation?.evaluation_run_id || "未绑定"}</span> : null}</div>{canWrite && version.status === "validated" ? <button onClick={() => { setSelected(version); setMode("submit"); setEvaluationId(""); setReason(""); setKey(""); }}>提交版本 {version.version_number}</button> : <span className={version.evaluation ? "gatePassed" : "gateBlocked"}>{version.evaluation ? "已绑定评测快照" : "不可发布：未绑定通过的评测"}</span>}</article>) : <p className="structuredEmpty">输入组织 ID 后展示服务端版本及门禁结果。</p>}{versionCursor ? <button onClick={() => void loadMoreVersions()}>加载更多版本</button> : null}</section>
      <section className="llmPanel"><h2>待发布版本</h2>{versions.filter((v) => v.status === "pending_publish").length ? versions.filter((v) => v.status === "pending_publish").map((version) => <article className="releaseCard" key={version.version_id}><div><strong>版本 {version.version_number}</strong><span>{version.version_id}</span><span>评测：<span>{version.evaluation?.evaluation_run_id || "未绑定"}</span></span></div>{canWrite ? <button disabled={!version.evaluation} onClick={() => { setSelected(version); setMode("publish"); setReason(""); setKey(""); }}>发布版本 {version.version_number}</button> : null}</article>) : <p className="structuredEmpty">暂无通过门禁并等待发布的版本。</p>}</section>
      <section className="llmPanel"><h2>发布记录</h2>{records.length ? records.map((record) => { const version = versions.find((item) => item.version_id === record.config_version_id); return <article className="releaseCard" key={record.release_record_id}><div><strong>{version ? `版本 ${version.version_number}` : "配置版本"} · {record.status} · revision {record.revision}</strong><span>发布记录：{record.release_record_id}</span><span>配置版本：{record.config_version_id}</span><span>提交：{new Date(record.submitted_at).toLocaleString()} · {record.submitted_by_system_admin_user_id}</span><span>发布：{record.published_at ? new Date(record.published_at).toLocaleString() : "—"} · {record.published_by_system_admin_user_id || "—"}</span><span>评测：{record.evaluation_run_id} / {record.evaluation_config_version_id}</span><span>回滚发布：{record.rollback_of_release_id || "—"}</span><span>回滚版本：{record.rollback_of_version_id || "—"}</span></div>{canWrite && version ? <button onClick={() => void rollback(version)}>回滚到此版本</button> : null}</article>; }) : <p className="structuredEmpty">服务端未返回已发布记录。</p>}{releaseCursor ? <button onClick={() => void loadMoreRecords()}>加载更多发布记录</button> : null}</section>
    </div>
    {selected ? <div className="releaseDialog" role="dialog" aria-modal="true" aria-labelledby="release-title"><div ref={dialogRef}><h2 id="release-title">{mode === "submit" ? "提交" : "发布"}版本 {selected.version_number}</h2>{mode === "submit" ? <label>评测快照 ID<input value={evaluationId} onChange={(event) => setEvaluationId(event.target.value)} /></label> : <p>评测快照：{selected.evaluation?.evaluation_run_id}</p>}<label>发布原因<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label><label>幂等键<input value={key} onChange={(event) => setKey(event.target.value)} /></label><div className="panelActions"><button onClick={() => setSelected(null)}>取消</button><button className="primaryAction" disabled={!reason.trim() || !key.trim() || (mode === "submit" && !evaluationId.trim())} onClick={() => void (mode === "submit" ? submit() : publish())}>{mode === "submit" ? "确认提交" : "确认发布"}</button></div></div></div> : null}
  </section>;
}
