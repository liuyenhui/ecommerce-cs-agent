import React from "react";
import { systemApi } from "../system-api";
import type { LlmReleaseRecord, LlmVersion } from "../system-types";
import { formatShanghaiDateTime } from "../../../shared/date-time";

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
  const controller = React.useRef<AbortController | null>(null); const versionMoreRequest = React.useRef<AbortController | null>(null); const releaseMoreRequest = React.useRef<AbortController | null>(null); const lookupRequest = React.useRef<AbortController | null>(null); const actionRequest = React.useRef<AbortController | null>(null); const generation = React.useRef(0);
  const versionMoreInFlight = React.useRef(false); const releaseMoreInFlight = React.useRef(false);
  const actionInFlight = React.useRef(false); const mounted = React.useRef(true);
  const [versionMoreBusy, setVersionMoreBusy] = React.useState(false); const [releaseMoreBusy, setReleaseMoreBusy] = React.useState(false); const [lookupBusy, setLookupBusy] = React.useState(""); const [actionBusy, setActionBusy] = React.useState(false);
  const dialogRef = React.useRef<HTMLDivElement | null>(null);
  const restoreFocus = React.useRef<HTMLElement | null>(null);
  React.useEffect(() => () => { mounted.current = false; controller.current?.abort(); versionMoreRequest.current?.abort(); releaseMoreRequest.current?.abort(); lookupRequest.current?.abort(); actionRequest.current?.abort(); }, []);

  const owns = (scope: string, owner: number, signal?: AbortSignal) => !signal?.aborted && owner === generation.current && scope === organizationId.trim();

  function openAction(version: LlmVersion, actionMode: "submit" | "publish") {
    const scope = organizationId.trim();
    if (!scope || version.organization_id !== scope) { setMessage("版本组织范围不匹配，请重新查询"); return; }
    setSelected(version); setMode(actionMode); setEvaluationId(""); setReason(""); setKey(`${actionMode}-${crypto.randomUUID()}`);
  }

  function changeOrganization(value: string) {
    if (actionInFlight.current) return;
    controller.current?.abort(); versionMoreRequest.current?.abort(); releaseMoreRequest.current?.abort(); lookupRequest.current?.abort(); actionRequest.current?.abort(); generation.current += 1;
    versionMoreInFlight.current = false; releaseMoreInFlight.current = false; setVersionMoreBusy(false); setReleaseMoreBusy(false);
    setLookupBusy(""); setActionBusy(false); actionInFlight.current = false; setVersions([]); setRecords([]); setVersionCursor(null); setReleaseCursor(null); setSelected(null); setMessage(""); setOrganizationId(value);
  }

  React.useEffect(() => {
    if (!selected) return;
    const dialog = dialogRef.current; const previous = document.activeElement as HTMLElement | null; restoreFocus.current = previous;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>("button,input,textarea") || []).filter((item) => !item.hasAttribute("disabled"));
    focusable()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { if (!actionInFlight.current) setSelected(null); return; }
      if (event.key !== "Tab") return;
      const items = focusable(); if (!items.length) return; const first = items[0]; const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    dialog?.addEventListener("keydown", onKey); return () => { dialog?.removeEventListener("keydown", onKey); restoreFocus.current?.focus(); };
  }, [selected]);

  async function load(preserve = false): Promise<boolean> {
    if (!organizationId.trim()) { setMessage("请输入组织 ID"); return false; }
    controller.current?.abort(); versionMoreRequest.current?.abort(); releaseMoreRequest.current?.abort(); lookupRequest.current?.abort(); versionMoreInFlight.current = false; releaseMoreInFlight.current = false; setVersionMoreBusy(false); setReleaseMoreBusy(false); setLookupBusy(""); const next = new AbortController(); controller.current = next; const current = ++generation.current; const scope = organizationId.trim();
    if (!preserve) { setVersions([]); setRecords([]); setVersionCursor(null); setReleaseCursor(null); setSelected(null); } setMessage("");
    try { const [versionData, releaseData] = await Promise.all([systemApi.llmVersions(scope, undefined, next.signal), systemApi.llmReleaseRecords(scope, undefined, next.signal)]); if (next.signal.aborted || current !== generation.current || scope !== organizationId.trim()) return false; setVersions(versionData.items); setRecords(releaseData.items); setVersionCursor(versionData.page_info.next_cursor); setReleaseCursor(releaseData.page_info.next_cursor); setMessage(""); return true; }
    catch (error) { if (!next.signal.aborted && current === generation.current && !preserve) setMessage(failure(error)); return false; }
  }
  async function loadMoreVersions() { if (!versionCursor || versionMoreInFlight.current) return; versionMoreInFlight.current = true; const current = generation.current; const scope = organizationId.trim(); const cursor = versionCursor; const next = new AbortController(); versionMoreRequest.current = next; setVersionMoreBusy(true); try { const data = await systemApi.llmVersions(scope, cursor, next.signal); if (!owns(scope, current, next.signal)) return; setVersions((items) => [...items, ...data.items]); setVersionCursor(data.page_info.next_cursor); } catch (error) { if (owns(scope, current, next.signal)) setMessage(`版本加载失败：${failure(error)}，可重试`); } finally { versionMoreInFlight.current = false; if (owns(scope, current)) setVersionMoreBusy(false); } }
  async function loadMoreRecords() { if (!releaseCursor || releaseMoreInFlight.current) return; releaseMoreInFlight.current = true; const current = generation.current; const scope = organizationId.trim(); const cursor = releaseCursor; const next = new AbortController(); releaseMoreRequest.current = next; setReleaseMoreBusy(true); try { const data = await systemApi.llmReleaseRecords(scope, cursor, next.signal); if (!owns(scope, current, next.signal)) return; setRecords((items) => [...items, ...data.items]); setReleaseCursor(data.page_info.next_cursor); } catch (error) { if (owns(scope, current, next.signal)) setMessage(`发布记录加载失败：${failure(error)}，可重试`); } finally { releaseMoreInFlight.current = false; if (owns(scope, current)) setReleaseMoreBusy(false); } }
  async function loadVersionForRecord(versionId: string) { lookupRequest.current?.abort(); const next = new AbortController(); lookupRequest.current = next; const current = generation.current; const scope = organizationId.trim(); setLookupBusy(versionId); try { const item = await systemApi.llmVersion(versionId, next.signal); if (!owns(scope, current, next.signal)) return; if (item.organization_id !== scope) throw new Error("版本组织范围不匹配"); setVersions((items) => items.some((version) => version.version_id === item.version_id) ? items : [...items, item]); setMessage("已加载发布记录对应版本，可执行回滚"); } catch (error) { if (owns(scope, current, next.signal)) setMessage(`对应版本加载失败：${failure(error)}`); } finally { if (owns(scope, current)) setLookupBusy(""); } }

  async function publish() {
    if (!selected || !reason.trim() || !key.trim()) { setMessage("发布原因和幂等键不能为空"); return; }
    if (actionInFlight.current) return; actionInFlight.current = true;
    if (!window.confirm(`确认发布版本 ${selected.version_number}？该操作会切换运行流量。`)) { actionInFlight.current = false; return; }
    const scope = organizationId.trim(); const current = generation.current; const target = selected; const intentKey = key.trim(); const next = new AbortController(); actionRequest.current = next; setActionBusy(true);
    try { await systemApi.publishLlmVersion(target.version_id, { expected_revision: target.revision, reason: reason.trim(), idempotency_key: intentKey }, next.signal); if (!owns(scope, current, next.signal)) return; setSelected(null); const refreshed = await load(true); if (!mounted.current || scope !== organizationId.trim()) return; setMessage(refreshed ? "版本已发布，列表已从服务端刷新" : "发布已成功，但列表刷新失败，请重试"); }
    catch (error) { if (owns(scope, current, next.signal)) setMessage(failure(error)); }
    finally { actionInFlight.current = false; if (mounted.current && scope === organizationId.trim()) setActionBusy(false); }
  }
  async function submit() {
    if (!selected || !evaluationId.trim() || !reason.trim() || !key.trim()) { setMessage("评测快照、发布原因和幂等键不能为空"); return; }
    if (actionInFlight.current) return; actionInFlight.current = true;
    if (!window.confirm(`确认以评测快照 ${evaluationId.trim()} 提交版本 ${selected.version_number}？`)) { actionInFlight.current = false; return; }
    const scope = organizationId.trim(); const current = generation.current; const target = selected; const intentKey = key.trim(); const evaluation = evaluationId.trim(); const next = new AbortController(); actionRequest.current = next; setActionBusy(true);
    try { await systemApi.submitLlmVersion(target.version_id, { expected_revision: target.revision, evaluation_run_id: evaluation, reason: reason.trim(), idempotency_key: intentKey }, next.signal); if (!owns(scope, current, next.signal)) return; setSelected(null); const refreshed = await load(true); if (!mounted.current || scope !== organizationId.trim()) return; setMessage(refreshed ? "版本已绑定评测快照，列表已从服务端刷新" : "提交已成功，但列表刷新失败，请重试"); }
    catch (error) { if (owns(scope, current, next.signal)) setMessage(failure(error)); }
    finally { actionInFlight.current = false; if (mounted.current && scope === organizationId.trim()) setActionBusy(false); }
  }
  async function rollback(version: LlmVersion) {
    if (actionInFlight.current) return; actionInFlight.current = true;
    const scope = organizationId.trim(); const current = generation.current;
    if (!scope || version.organization_id !== scope) { actionInFlight.current = false; setMessage("版本组织范围不匹配，请重新查询"); return; }
    const rollbackReason = window.prompt(`请输入回滚到版本 ${version.version_number} 的原因`)?.trim(); if (!rollbackReason) { actionInFlight.current = false; return; }
    if (!window.confirm(`确认创建并发布版本 ${version.version_number} 的回滚副本？`)) { actionInFlight.current = false; return; }
    const intentKey = `rollback-${crypto.randomUUID()}`; const next = new AbortController(); actionRequest.current = next; setActionBusy(true);
    try { await systemApi.rollbackLlmVersion(version.version_id, { reason: rollbackReason, idempotency_key: intentKey }, next.signal); if (!owns(scope, current, next.signal)) return; const refreshed = await load(true); if (!mounted.current || scope !== organizationId.trim()) return; setMessage(refreshed ? "回滚已完成，版本与发布记录已从服务端刷新" : "回滚已成功，但列表刷新失败，请重试"); }
    catch (error) { if (owns(scope, current, next.signal)) setMessage(failure(error)); }
    finally { actionInFlight.current = false; if (mounted.current && scope === organizationId.trim()) setActionBusy(false); }
  }

  return <section className="llmPage"><header className="pageHeading"><div><h1>评测与发布</h1><p>发布只使用真实版本记录及其已绑定评测快照；当前契约不提供独立评测运行列表。</p></div></header>
    <div className="organizationLoader"><label>组织 ID<input value={organizationId} disabled={Boolean(selected) || actionBusy} onChange={(event) => changeOrganization(event.target.value)} /></label><button disabled={actionBusy} onClick={() => void load(false)}>查询版本</button></div>
    {message ? <div className="llmNotice" role="status">{message}</div> : null}
    <div className="releaseGrid">
      <section className="llmPanel"><h2>评测运行与门禁</h2>{versions.length ? versions.map((version) => <article className="releaseCard" key={version.version_id}><div><strong>版本 {version.version_number}</strong><span>状态：{version.status}</span>{version.status !== "pending_publish" ? <span>评测快照：{version.evaluation?.evaluation_run_id || "未绑定"}</span> : null}</div>{canWrite && version.status === "validated" ? <button disabled={actionBusy} onClick={() => openAction(version, "submit")}>提交版本 {version.version_number}</button> : <span className={version.evaluation ? "gatePassed" : "gateBlocked"}>{version.evaluation ? "已绑定评测快照" : "不可发布：未绑定通过的评测"}</span>}</article>) : <p className="structuredEmpty">输入组织 ID 后展示服务端版本及门禁结果。</p>}{versionCursor ? <button disabled={versionMoreBusy} onClick={() => void loadMoreVersions()}>{versionMoreBusy ? "加载中…" : "加载更多版本"}</button> : null}</section>
      <section className="llmPanel"><h2>待发布版本</h2>{versions.filter((v) => v.status === "pending_publish").length ? versions.filter((v) => v.status === "pending_publish").map((version) => <article className="releaseCard" key={version.version_id}><div><strong>版本 {version.version_number}</strong><span>{version.version_id}</span><span>评测：<span>{version.evaluation?.evaluation_run_id || "未绑定"}</span></span></div>{canWrite ? <button disabled={!version.evaluation || actionBusy} onClick={() => openAction(version, "publish")}>发布版本 {version.version_number}</button> : null}</article>) : <p className="structuredEmpty">暂无通过门禁并等待发布的版本。</p>}</section>
      <section className="llmPanel"><h2>发布记录</h2>{records.length ? records.map((record) => { const version = versions.find((item) => item.version_id === record.config_version_id); return <article className="releaseCard" key={record.release_record_id}><div><strong>{version ? `版本 ${version.version_number}` : "配置版本"} · {record.status} · revision {record.revision}</strong><span>发布记录：{record.release_record_id}</span><span>配置版本：{record.config_version_id}</span><span>提交：{formatShanghaiDateTime(record.submitted_at)} · {record.submitted_by_system_admin_user_id}</span><span>发布：{formatShanghaiDateTime(record.published_at)} · {record.published_by_system_admin_user_id || "—"}</span><span>评测：{record.evaluation_run_id} / {record.evaluation_config_version_id}</span><span>回滚发布：{record.rollback_of_release_id || "—"}</span><span>回滚版本：{record.rollback_of_version_id || "—"}</span></div>{canWrite && version ? <button disabled={actionBusy} onClick={() => void rollback(version)}>{actionBusy ? "回滚中…" : "回滚到此版本"}</button> : canWrite ? <button disabled={lookupBusy === record.config_version_id || actionBusy} onClick={() => void loadVersionForRecord(record.config_version_id)}>{lookupBusy === record.config_version_id ? "加载中…" : "加载对应版本后回滚"}</button> : null}</article>; }) : <p className="structuredEmpty">服务端未返回已发布记录。</p>}{releaseCursor ? <button disabled={releaseMoreBusy} onClick={() => void loadMoreRecords()}>{releaseMoreBusy ? "加载中…" : "加载更多发布记录"}</button> : null}</section>
    </div>
    {selected ? <div className="releaseDialog" role="dialog" aria-modal="true" aria-labelledby="release-title"><div ref={dialogRef}><h2 id="release-title">{mode === "submit" ? "提交" : "发布"}版本 {selected.version_number}</h2><p>组织范围：{selected.organization_id}</p>{mode === "submit" ? <label>评测快照 ID<input disabled={actionBusy} value={evaluationId} onChange={(event) => setEvaluationId(event.target.value)} /></label> : <p>评测快照：{selected.evaluation?.evaluation_run_id}</p>}<label>发布原因<textarea disabled={actionBusy} value={reason} onChange={(event) => setReason(event.target.value)} /></label><label>幂等键<input disabled={actionBusy} value={key} onChange={(event) => setKey(event.target.value)} /></label><div className="panelActions"><button disabled={actionBusy} onClick={() => setSelected(null)}>取消</button><button className="primaryAction" disabled={actionBusy || !reason.trim() || !key.trim() || (mode === "submit" && !evaluationId.trim())} onClick={() => void (mode === "submit" ? submit() : publish())}>{actionBusy ? (mode === "submit" ? "提交中…" : "发布中…") : (mode === "submit" ? "确认提交" : "确认发布")}</button></div></div></div> : null}
  </section>;
}
