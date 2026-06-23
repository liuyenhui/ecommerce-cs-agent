import React from "react";
import {
  AlertTriangle,
  KeyRound,
  ListFilter,
  Loader2,
  LogOut,
  ShieldCheck
} from "lucide-react";
import { buildSystemUserSummary, fieldLabel, renderCell, tableEmptyState } from "./data";
import type { EmptyStateProps, JsonRecord, NavItem, ToastState } from "./types";

export function useCloseOnEscape(open: boolean, close: () => void) {
  React.useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open, close]);
}

export function AdminFrame({
  isAuthenticated,
  mobileNavOpen,
  brand,
  navigation,
  topBar,
  children,
  toast,
  onCloseNav,
  onCloseToast
}: {
  isAuthenticated: boolean;
  mobileNavOpen: boolean;
  brand: React.ReactNode;
  navigation: React.ReactNode;
  topBar: React.ReactNode;
  children: React.ReactNode;
  toast: ToastState;
  onCloseNav: () => void;
  onCloseToast: () => void;
}) {
  return (
    <main className={`appShell ${isAuthenticated ? "isAuthed" : "isGuest"} ${mobileNavOpen ? "navOpen" : ""}`}>
      {isAuthenticated ? (
        <aside className="rail">
          <div className="brandMark">
            <ShieldCheck size={22} />
            <span>{brand}</span>
          </div>
          {navigation}
        </aside>
      ) : null}
      {isAuthenticated ? <button className="navBackdrop" aria-label="关闭导航" onClick={onCloseNav} /> : null}

      <section className="mainPane">
        {topBar}
        {children}
      </section>

      {toast ? <Toast toast={toast} onClose={onCloseToast} /> : null}
    </main>
  );
}

export function Navigation<T extends string>({
  items,
  activeTab,
  onChange,
  ariaLabel,
  defaultGroup,
  onNavigate
}: {
  items: Array<NavItem<T>>;
  activeTab: T;
  onChange: (tab: T) => void;
  ariaLabel: string;
  defaultGroup?: string;
  onNavigate?: () => void;
}) {
  const groups = Array.from(new Set(items.map((item) => item.group || defaultGroup || "")));
  return (
    <nav className="navList" aria-label={ariaLabel}>
      {groups.map((group) => (
        <React.Fragment key={group || "default"}>
          {group ? <span className="navGroup">{group}</span> : null}
          {items.filter((item) => (item.group || defaultGroup || "") === group).map((item) => (
            <button key={item.key} className={activeTab === item.key ? "active" : ""} onClick={() => {
              onChange(item.key);
              onNavigate?.();
            }}>
              {item.icon}<span>{item.label}</span>
            </button>
          ))}
        </React.Fragment>
      ))}
    </nav>
  );
}

export function TopBar({
  eyebrow,
  title,
  subtitle,
  showNavButton,
  navOpen,
  onToggleNav,
  onLogout
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  showNavButton: boolean;
  navOpen: boolean;
  onToggleNav: () => void;
  onLogout: () => void;
}) {
  return (
    <header className="topBar">
      <div className="topTitle">
        {showNavButton ? (
          <button className="mobileNavButton" type="button" onClick={onToggleNav} aria-label={navOpen ? "关闭后台导航" : "打开后台导航"} aria-expanded={navOpen}>
            <ListFilter size={17} />
          </button>
        ) : null}
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
      </div>
      {showNavButton ? (
        <div className="topActions">
          <button className="iconButton" onClick={onLogout} title="退出登录">
            <LogOut size={16} />退出
          </button>
        </div>
      ) : null}
    </header>
  );
}

export function LoginPanelBase({
  title,
  initialError,
  onLoggedIn,
  onSubmit,
  secondaryAction,
  setToast
}: {
  title: string;
  initialError?: string | null;
  onLoggedIn: (session: JsonRecord) => void;
  onSubmit: (email: string, password: string) => Promise<JsonRecord>;
  secondaryAction?: {
    label: string;
    onClick: () => void;
    icon?: React.ReactNode;
  };
  setToast: (toast: ToastState) => void;
}) {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [loginError, setLoginError] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Partial<Record<"email" | "password", boolean>>>({});
  const [loading, setLoading] = React.useState(false);
  const loginErrorId = `${title.replace(/\s+/g, "-")}-login-error`;
  const authErrorText = "邮箱或密码错误，请检查后重试。";

  React.useEffect(() => {
    setLoginError(initialError || null);
  }, [initialError]);

  function clearLoginError() {
    if (loginError) setLoginError(null);
    if (Object.keys(fieldErrors).length) setFieldErrors({});
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoginError(null);
    const nextFieldErrors = {
      email: !email.trim(),
      password: !password
    };
    if (nextFieldErrors.email || nextFieldErrors.password) {
      setFieldErrors(nextFieldErrors);
      setLoginError("请填写邮箱和密码");
      return;
    }
    setFieldErrors({});
    setLoading(true);
    try {
      const session = await onSubmit(email.trim(), password);
      onLoggedIn(session);
      setToast({ tone: "success", text: "登录成功" });
    } catch (error) {
      setLoginError(loginFailureMessage(error, authErrorText));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="loginSurface">
      <form className="loginPanel" onSubmit={submit}>
        <KeyRound size={24} />
        <h2>{title}</h2>
        <label>
          邮箱
          <input
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
              clearLoginError();
            }}
            autoComplete="username"
            inputMode="email"
            placeholder="name@example.com"
            aria-invalid={Boolean(fieldErrors.email)}
            aria-describedby={loginError && fieldErrors.email ? loginErrorId : undefined}
          />
        </label>
        <label>
          密码
          <input
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              clearLoginError();
            }}
            type="password"
            autoComplete="current-password"
            aria-invalid={Boolean(fieldErrors.password)}
            aria-describedby={loginError && fieldErrors.password ? loginErrorId : undefined}
          />
        </label>
        {loginError ? (
          <div className="loginError" id={loginErrorId} role="alert">
            <AlertTriangle size={16} />
            <span>{loginError}</span>
          </div>
        ) : null}
        <button className="primaryButton" type="submit" disabled={loading}>
          {loading ? <Loader2 size={16} className="spin" /> : <ShieldCheck size={16} />}
          登录
        </button>
        {secondaryAction ? (
          <button className="secondaryLoginButton" type="button" onClick={secondaryAction.onClick} disabled={loading}>
            {secondaryAction.icon || <KeyRound size={16} />}
            {secondaryAction.label}
          </button>
        ) : null}
      </form>
    </section>
  );
}

function loginFailureMessage(error: unknown, authErrorText: string): string {
  const message = error instanceof Error ? error.message : String(error || "");
  if (message.startsWith("401 ")) return authErrorText;
  return "登录失败，请稍后重试。";
}

export function SectionHeader({ label, title, action }: { label: string; title: string; action?: React.ReactNode }) {
  return (
    <div className="sectionHeader">
      <div>
        <p className="eyebrow">{label}</p>
        <h2>{title}</h2>
      </div>
      {action ? <div className="sectionActions">{action}</div> : null}
    </div>
  );
}

export function Metric({ label, value, tone }: { label: string; value: string; tone: "ok" | "warn" | "bad" | "info" }) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </div>
  );
}

export function DataTable({ title, rows, fields, onSelect, action, emptyState }: {
  title: string;
  rows: JsonRecord[];
  fields: string[];
  onSelect?: (record: JsonRecord) => void;
  action?: (record: JsonRecord) => React.ReactNode;
  emptyState?: EmptyStateProps;
}) {
  return (
    <section className="tablePanel">
      <h3>{title}</h3>
      {rows.length ? (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>{fields.map((field) => <th key={field}>{fieldLabel(field)}</th>)}{action ? <th>操作</th> : null}</tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={String(row.id || row.decision_id || row.task_id || index)} onClick={() => onSelect?.(row)}>
                  {fields.map((field) => <td key={field} data-label={fieldLabel(field)}>{renderCell(row[field])}</td>)}
                  {action ? <td data-label="操作" onClick={(event) => event.stopPropagation()}>{action(row)}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyState {...(emptyState || tableEmptyState(title))} />}
    </section>
  );
}

export function AuditTable({ title, rows, onSelect }: { title: string; rows: JsonRecord[]; onSelect: (record: JsonRecord) => void }) {
  return <DataTable title={title} rows={rows} fields={["audit_log_id", "action", "object_type", "reason", "created_at"]} onSelect={onSelect} />;
}

export function ListPanel({ title, rows, fields, emptyState }: { title: string; rows: JsonRecord[]; fields: string[]; emptyState?: EmptyStateProps }) {
  return <DataTable title={title} rows={rows} fields={fields} emptyState={emptyState} />;
}

export function ContextPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <aside className="contextPanel">
      <h2>{title}</h2>
      {children}
    </aside>
  );
}

export function SystemUserSummary({ user }: { user: JsonRecord }) {
  const items = buildSystemUserSummary(user);
  if (!items.length) return <p className="emptyText">暂无账号摘要</p>;
  return (
    <section className="userSummary" aria-label="当前系统账号摘要">
      <h3>当前账号</h3>
      <dl>
        {items.map((item) => (
          <div key={item.label}>
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function Drawer({ title, record, onClose }: { title: string; record: JsonRecord; onClose: () => void }) {
  return (
    <aside className="drawer">
      <div className="drawerHeader">
        <h2>{title}</h2>
        <button onClick={onClose}>关闭</button>
      </div>
      <pre>{JSON.stringify(record, null, 2)}</pre>
    </aside>
  );
}

export function Toast({ toast, onClose }: { toast: NonNullable<ToastState>; onClose: () => void }) {
  React.useEffect(() => {
    const timer = window.setTimeout(onClose, 3200);
    return () => window.clearTimeout(timer);
  }, [onClose]);
  return <div className={`toast ${toast.tone}`}>{toast.text}</div>;
}

export function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label>
      {label}
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

export function RecordSummary({ record }: { record: unknown }) {
  if (!record) return <p className="emptyText">暂无记录</p>;
  return <pre className="recordSummary">{JSON.stringify(record, null, 2)}</pre>;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="emptyState">
      <strong>{title || "暂无记录"}</strong>
      <p>{description || "当前没有可展示的数据；调整筛选条件或完成配置后再查看。"}</p>
      {action ? <div className="emptyAction">{action}</div> : null}
    </div>
  );
}
