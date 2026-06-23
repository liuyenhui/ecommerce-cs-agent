import type React from "react";

export type JsonRecord = Record<string, unknown>;
export type ToastState = { tone: "success" | "error" | "info"; text: string } | null;
export type EmptyStateProps = { title?: string; description?: string; action?: React.ReactNode };

export type Page<T = JsonRecord> = {
  items?: T[];
  organizations?: T[];
  stores?: T[];
  page_info?: JsonRecord;
};

export type NavItem<T extends string> = {
  key: T;
  label: string;
  group?: string;
  icon: React.ReactNode;
};
