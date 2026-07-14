import React from "react";
import { RefreshCw } from "lucide-react";
import { DataTable, RequestStateView, SectionHeader } from "../../../shared/components";
import type { PageEnvelope, RequestState, TaskRecord } from "../system-types";
import { PaginationControls } from "./PaginationControls";

export function TasksPage({ state, onRetry, onPageChange = () => undefined }: { state: RequestState<PageEnvelope<TaskRecord>>; onRetry: (task: TaskRecord) => void; onPageChange?: (page: number) => void }) {
  return <RequestStateView state={state}>{(data) => <>
    <SectionHeader label="TASKS" title="任务中心" />
    <p className="pageTotal">共 {data.page.total} 个任务</p>
    <DataTable title="后台任务" rows={data.items} fields={["task_id", "task_type", "status", "retryable", "updated_at"]} action={(row) => row.status === "failed" && row.retryable === true ? <button type="button" onClick={() => onRetry(row as TaskRecord)}><RefreshCw size={15} />重试</button> : null} emptyState={{ title: "暂无任务", description: "服务端未返回符合筛选条件的任务。" }} />
    <PaginationControls page={data.page} onPageChange={onPageChange} />
  </>}</RequestStateView>;
}
