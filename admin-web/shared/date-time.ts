export const ADMIN_TIME_ZONE = "Asia/Shanghai";

const shanghaiDateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: ADMIN_TIME_ZONE,
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23"
});

export function formatShanghaiDateTime(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  const date = value instanceof Date ? value : new Date(String(value));
  if (Number.isNaN(date.getTime())) return fallback;

  const parts = Object.fromEntries(
    shanghaiDateTimeFormatter.formatToParts(date).map((part) => [part.type, part.value])
  );
  return `${parts.year}年${Number(parts.month)}月${Number(parts.day)}日 ${parts.hour}:${parts.minute}:${parts.second}`;
}

export function isDateTimeField(field: string) {
  return field === "timestamp" || field.endsWith("_timestamp") || field.endsWith("_at");
}
