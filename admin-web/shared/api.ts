import type { JsonRecord } from "./types";

export async function requestJson<T = JsonRecord>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    credentials: "include",
    ...options,
    headers
  });
  if (response.status === 204) return null as T;
  const contentType = response.headers.get("Content-Type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "object" && payload && "error" in payload
      ? String(((payload as JsonRecord).error as JsonRecord | undefined)?.message || response.statusText)
      : String(payload || response.statusText);
    throw new Error(`${response.status} ${message}`);
  }
  return payload as T;
}
