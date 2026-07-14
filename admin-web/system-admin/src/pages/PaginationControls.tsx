import React from "react";
import type { PageMeta } from "../system-types";

export function PaginationControls({ page, onPageChange }: { page: PageMeta; onPageChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(page.total / page.page_size));
  return <nav className="paginationControls" aria-label="分页">
    <button type="button" disabled={page.page <= 1} onClick={() => onPageChange(page.page - 1)}>上一页</button>
    <span>第 {page.page} / {pages} 页，共 {page.total} 条</span>
    <button type="button" disabled={page.page >= pages} onClick={() => onPageChange(page.page + 1)}>下一页</button>
  </nav>;
}
