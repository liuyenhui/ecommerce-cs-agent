import React from "react";
import { createRoot } from "react-dom/client";
import { Activity, Boxes, ClipboardList, Database, ShieldCheck, Store, Users } from "lucide-react";
import "./styles.css";

type ApiState = {
  customer: Record<string, unknown> | null;
  system: Record<string, unknown> | null;
  traces: Record<string, unknown>[];
  audit: Record<string, unknown>[];
  health: Record<string, unknown> | null;
  error: string | null;
};

const jsonHeaders = { "Content-Type": "application/json" };

async function postJson(path: string, body: unknown) {
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: jsonHeaders,
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error(`${path} ${response.status}`);
  return response.status === 204 ? null : response.json();
}

async function getJson(path: string) {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) throw new Error(`${path} ${response.status}`);
  return response.json();
}

function App() {
  const [state, setState] = React.useState<ApiState>({
    customer: null,
    system: null,
    traces: [],
    audit: [],
    health: null,
    error: null
  });

  async function loadCustomer() {
    try {
      await postJson("/v1/admin/auth/login", {
        email: "admin@example.test",
        password: "admin-password",
        organization_id: "org-001"
      });
      const [customer, audit] = await Promise.all([
        getJson("/v1/admin/auth/me"),
        getJson("/v1/admin/audit-logs?organization_id=org-001")
      ]);
      setState((current) => ({ ...current, customer, audit: audit.items ?? [], error: null }));
    } catch (error) {
      setState((current) => ({ ...current, error: String(error) }));
    }
  }

  async function loadSystem() {
    try {
      await postJson("/v1/system-admin/auth/login", {
        email: "system-admin@example.test",
        password: "system-admin-password"
      });
      const [system, health, traces] = await Promise.all([
        getJson("/v1/system-admin/auth/me"),
        getJson("/v1/system-admin/health"),
        getJson("/v1/system-admin/message-traces")
      ]);
      setState((current) => ({ ...current, system, health, traces: traces.items ?? [], error: null }));
    } catch (error) {
      setState((current) => ({ ...current, error: String(error) }));
    }
  }

  React.useEffect(() => {
    void loadCustomer();
    void loadSystem();
  }, []);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <ShieldCheck size={22} />
          <span>Ecommerce CS Agent</span>
        </div>
        <nav>
          <a href="#customer"><Store size={18} />客户后台</a>
          <a href="#product"><Boxes size={18} />商品资料</a>
          <a href="#system"><Activity size={18} />系统后台</a>
          <a href="#audit"><ClipboardList size={18} />审计</a>
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>客户与系统管理</h1>
            <p>v1 后台运行视图</p>
          </div>
          <div className="actions">
            <button onClick={loadCustomer}><Users size={16} />刷新客户</button>
            <button onClick={loadSystem}><Database size={16} />刷新系统</button>
          </div>
        </header>

        {state.error ? <div className="alert">{state.error}</div> : null}

        <div className="grid">
          <Panel id="customer" title="客户后台" icon={<Store size={18} />}>
            <KeyValue label="用户" value={read(state.customer, "user.display_name")} />
            <KeyValue label="组织" value={read(state.customer, "active_organization_id")} />
            <KeyValue label="店铺" value={read(state.customer, "active_store_id")} />
          </Panel>
          <Panel id="product" title="商品资料" icon={<Boxes size={18} />}>
            <KeyValue label="资料入口" value="/v1/product-content/products" />
            <KeyValue label="资产归档" value="/v1/product-content/assets" />
            <KeyValue label="知识审核" value="/v1/product-content/knowledge-candidates" />
          </Panel>
          <Panel id="system" title="系统后台" icon={<Activity size={18} />}>
            <KeyValue label="状态" value={read(state.health, "status")} />
            <KeyValue label="系统用户" value={read(state.system, "user.display_name")} />
            <KeyValue label="Trace 数" value={String(state.traces.length)} />
          </Panel>
          <Panel id="audit" title="审计" icon={<ClipboardList size={18} />}>
            <Table rows={state.audit.slice(0, 5)} />
          </Panel>
        </div>

        <section className="wide">
          <h2>消息 Trace</h2>
          <Table rows={state.traces.slice(0, 8)} />
        </section>
      </section>
    </main>
  );
}

function Panel({ id, title, icon, children }: { id: string; title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section id={id} className="panel">
      <h2>{icon}{title}</h2>
      {children}
    </section>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="kv">
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </div>
  );
}

function Table({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return <p className="empty">暂无记录</p>;
  const keys = Object.keys(rows[0]).slice(0, 5);
  return (
    <div className="tableWrap">
      <table>
        <thead><tr>{keys.map((key) => <th key={key}>{key}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>{keys.map((key) => <td key={key}>{format(row[key])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function read(source: Record<string, unknown> | null, path: string) {
  if (!source) return "";
  return path.split(".").reduce<unknown>((value, key) => {
    if (value && typeof value === "object" && key in value) return (value as Record<string, unknown>)[key];
    return "";
  }, source) as string;
}

function format(value: unknown) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

createRoot(document.getElementById("root")!).render(<App />);
