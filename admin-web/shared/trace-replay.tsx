import React from "react";
import { readRecord } from "./data";
import { presentDecisionTrace } from "./trace-presentation";
import type { JsonRecord } from "./types";

type TraceNode = JsonRecord & {
  id: string;
  label?: string;
  kind?: string;
  status?: string;
  started_at?: string;
  ended_at?: string;
  inputs_ref?: unknown;
  outputs_ref?: unknown;
  error?: unknown;
};

type TraceEdge = JsonRecord & {
  source: string;
  target: string;
  label?: string;
  condition?: string;
  taken?: boolean;
};

type TraceGraph = {
  nodes: TraceNode[];
  edges: TraceEdge[];
};

type FlowNodeView = {
  node: TraceNode;
  x: number;
  y: number;
  width: number;
  height: number;
  tone: "done" | "current" | "blocked" | "skipped" | "pending";
  statusText: string;
  note: string;
};

const knownLayout: Record<string, { x: number; y: number; width?: number; height?: number }> = {
  normalize_request: { x: 290, y: 24 },
  retrieve_context: { x: 290, y: 128 },
  classify_intent: { x: 290, y: 232 },
  context_gate: { x: 290, y: 350, height: 76 },
  action_gate: { x: 290, y: 478, height: 76 },
  generate_candidate: { x: 290, y: 606 },
  policy_gate: { x: 290, y: 724, height: 76 },
  persist_trace: { x: 290, y: 848 },
  missing_context: { x: 28, y: 378 },
  action_request: { x: 552, y: 514 },
  handoff: { x: 552, y: 720 },
  auto_reply: { x: 28, y: 842 }
};

const statusLabel: Record<string, string> = {
  completed: "已完成",
  running: "运行中",
  failed: "失败",
  skipped: "未走此分支",
  pending: "等待中",
  action_request: "等待动作",
  context_request: "缺少上下文",
  handoff: "转人工",
  answer_ready: "可回复"
};

const nodeToneStyle = {
  done: { fill: "#dcfce7", stroke: "#16a34a", title: "#14532d", text: "#166534" },
  current: { fill: "#dbeafe", stroke: "#2563eb", title: "#1e3a8a", text: "#1d4ed8" },
  blocked: { fill: "#fee2e2", stroke: "#ef4444", title: "#7f1d1d", text: "#991b1b" },
  skipped: { fill: "#f8fafc", stroke: "#94a3b8", title: "#475569", text: "#64748b" },
  pending: { fill: "#fef3c7", stroke: "#f59e0b", title: "#78350f", text: "#92400e" }
};

type DecisionTraceReplayProps = {
  trace: unknown;
  action?: unknown;
  status?: unknown;
  risk?: unknown;
  missingContext?: unknown;
};

export function DecisionTraceReplay({ trace, action, status, risk, missingContext }: DecisionTraceReplayProps) {
  const graphData = React.useMemo(() => readTraceGraph(trace), [trace]);
  const presentation = presentDecisionTrace({
    action,
    status,
    risk,
    missingContext: Array.isArray(missingContext) && missingContext.length ? missingContext : inferMissingContext(graphData)
  });
  const rawStatus = String(status || action || "");
  const currentNodeId = findCurrentNodeId(graphData, presentation.currentNodeId, rawStatus);
  const blocker = describeBlocker(graphData, rawStatus, currentNodeId);
  const [graphUnavailable, setGraphUnavailable] = React.useState(false);
  const handleGraphUnavailable = React.useCallback(() => setGraphUnavailable(true), []);
  const handleGraphAvailable = React.useCallback(() => setGraphUnavailable(false), []);
  const [selectedNodeId, setSelectedNodeId] = React.useState(() => currentNodeId || graphData.nodes[0]?.id || "");
  const selectedNode = graphData.nodes.find((node) => node.id === selectedNodeId) || graphData.nodes.find((node) => node.id === currentNodeId) || graphData.nodes[0] || null;

  React.useEffect(() => {
    if (!graphData.nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(currentNodeId || graphData.nodes[0]?.id || "");
    }
  }, [graphData.nodes, currentNodeId, selectedNodeId]);

  React.useEffect(() => {
    setGraphUnavailable(false);
  }, [trace]);

  return (
    <section className="traceReplay" aria-label="LangGraph 单条消息运行回放">
      <div className={`traceProgressBanner ${["context_gate", "action_gate"].includes(currentNodeId) || presentation.title === "转人工处理" ? "blocked" : "active"}`}>
        <strong>{presentation.title}</strong>
        <span>{presentation.explanation || blocker}</span>
        <em>当前：{businessNodeLabel(currentNodeId)}</em>
      </div>
      <details className="traceTechnicalDetails">
        <summary>技术详情</summary>
        <div className="traceReplayMeta">
          <span>thread_id: {String(readRecord(trace, "graph").thread_id || readRecord(trace, "trace").thread_id || (trace as JsonRecord | undefined)?.thread_id || "-")}</span>
          <span>graph_version: {String((trace as JsonRecord | undefined)?.graph_version || "-")}</span>
          <span>status: {rawStatus || "-"}</span>
        </div>
      </details>
      {graphUnavailable ? <p className="traceGraphFallback" role="status">流程图暂时无法显示，请查看下方节点时间线。</p> : null}
      <DecisionFlowGraph
        graphData={graphData}
        status={rawStatus}
        selectedNodeId={selectedNode?.id || ""}
        currentNodeId={currentNodeId}
        blocker={blocker}
        onSelect={setSelectedNodeId}
        onUnavailable={handleGraphUnavailable}
        onAvailable={handleGraphAvailable}
      />
      <ol className="traceTimeline" aria-label="节点时间线">
        {graphData.nodes.map((node) => {
          const nodeBlocker = describeNodeBlocker(node, rawStatus);
          return (
            <li key={node.id} className={node.id === selectedNode?.id ? "active" : ""}>
              <button type="button" onClick={() => setSelectedNodeId(node.id)}>
                <strong title={node.label || node.id}>{businessNodeLabel(node.id, node.label)}</strong>
                <span title={String(node.status || "completed")}>{nodeBlocker || statusLabel[String(node.status || "completed")] || String(node.status || "completed")}</span>
              </button>
            </li>
          );
        })}
      </ol>
      {selectedNode ? <TraceNodeDetail node={selectedNode} status={rawStatus} /> : <p className="emptyText">暂无可回放节点</p>}
    </section>
  );
}

function DecisionFlowGraph({
  graphData,
  status,
  selectedNodeId,
  currentNodeId,
  blocker,
  onSelect,
  onUnavailable,
  onAvailable
}: {
  graphData: TraceGraph;
  status?: string;
  selectedNodeId: string;
  currentNodeId: string;
  blocker: string;
  onSelect: (nodeId: string) => void;
  onUnavailable: () => void;
  onAvailable: () => void;
}) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const graphRef = React.useRef<any>(null);

  React.useEffect(() => {
    if (!containerRef.current) return undefined;
    let disposed = false;
    let graph: any = null;

    void import("@antv/x6").then(({ Graph }) => {
      if (disposed || !containerRef.current) return;
      Graph.registerNode("decision-flow-node", {
        inherit: "rect",
        width: 230,
        height: 68,
        markup: [
          { tagName: "rect", selector: "body" },
          { tagName: "text", selector: "title" },
          { tagName: "text", selector: "status" },
          { tagName: "text", selector: "note" }
        ],
        attrs: {
          body: {
            refWidth: "100%",
            refHeight: "100%",
            rx: 7,
            ry: 7,
            strokeWidth: 2,
            cursor: "pointer"
          },
          title: {
            refX: 16,
            refY: 22,
            textAnchor: "start",
            textVerticalAnchor: "middle",
            fontSize: 13,
            fontWeight: 800,
            letterSpacing: 0,
            pointerEvents: "none"
          },
          status: {
            refX: 16,
            refY: 42,
            textAnchor: "start",
            textVerticalAnchor: "middle",
            fontSize: 11,
            fontWeight: 760,
            letterSpacing: 0,
            pointerEvents: "none"
          },
          note: {
            refX: 16,
            refY: 59,
            textAnchor: "start",
            textVerticalAnchor: "middle",
            fontSize: 10,
            fontWeight: 560,
            letterSpacing: 0,
            pointerEvents: "none"
          }
        }
      }, true);

      const width = Math.max(containerRef.current.clientWidth || 820, 760);
      graph = new Graph({
        container: containerRef.current,
        width,
        height: 960,
        interacting: false,
        panning: false,
        mousewheel: false,
        background: { color: "#020617" },
        grid: false
      });
      graphRef.current = graph;
      const activeGraph = graph;
      const nodeViews = layoutGraphNodes(graphData, currentNodeId, status, blocker);
      const nodeRefs = new Map<string, any>();

      nodeViews.forEach((item) => {
        const style = nodeToneStyle[item.tone];
        const ref = activeGraph.addNode({
          id: item.node.id,
          shape: "decision-flow-node",
          x: item.x,
          y: item.y,
          width: item.width,
          height: item.height,
          zIndex: 30,
          attrs: {
            body: {
              fill: style.fill,
              stroke: item.node.id === selectedNodeId ? "#0f172a" : style.stroke,
              strokeWidth: item.node.id === selectedNodeId ? 3 : 2
            },
            title: { text: businessNodeLabel(item.node.id, item.node.label), fill: style.title },
            status: { text: item.statusText, fill: style.text },
            note: { text: item.note, fill: style.text }
          }
        });
        if (ref) nodeRefs.set(item.node.id, ref);
      });

      graphData.edges.forEach((edge) => {
        const source = nodeRefs.get(edge.source);
        const target = nodeRefs.get(edge.target);
        if (!source || !target) return;
        const taken = Boolean(edge.taken);
        activeGraph.addEdge({
          source,
          target,
          labels: edge.label ? [
            {
              attrs: {
                label: {
                  text: edge.label,
                  fontSize: 10,
                  fontWeight: 800,
                  fill: taken ? "#dbeafe" : "#94a3b8"
                },
                rect: {
                  fill: taken ? "#1e293b" : "#f8fafc",
                  stroke: taken ? "#60a5fa" : "#cbd5e1",
                  rx: 4,
                  ry: 4
                }
              }
            }
          ] : undefined,
          attrs: {
            line: {
              class: edge.taken ? "trace-flow-edge active" : "trace-flow-edge inactive",
              stroke: taken ? "#38bdf8" : "#64748b",
              strokeWidth: taken ? 2.4 : 1.4,
              strokeDasharray: taken ? "10 7" : "5 7",
              targetMarker: {
                name: "block",
                width: 8,
                height: 7,
                fill: taken ? "#38bdf8" : "#64748b",
                stroke: taken ? "#38bdf8" : "#64748b"
              }
            }
          },
          connector: { name: "normal" },
          router: { name: "manhattan", args: { padding: 20 } },
          zIndex: taken ? 12 : 8
        });
      });

      activeGraph.on("node:click", ({ node }: { node?: { id?: string } }) => {
        if (node?.id) onSelect(String(node.id));
      });
      activeGraph.centerContent();
      onAvailable();
    }).catch(() => {
      if (!disposed) onUnavailable();
    });
    return () => {
      disposed = true;
      graph?.dispose();
      if (graphRef.current === graph) graphRef.current = null;
    };
  }, [graphData, status, currentNodeId, blocker, onSelect, onUnavailable, onAvailable]);

  React.useEffect(() => {
    const nodeViews = layoutGraphNodes(graphData, currentNodeId, status, blocker);
    nodeViews.forEach((item) => {
      const cell = graphRef.current?.getCellById(item.node.id);
      if (!cell) return;
      const style = nodeToneStyle[item.tone];
      cell.attr("body/stroke", item.node.id === selectedNodeId ? "#0f172a" : style.stroke);
      cell.attr("body/strokeWidth", item.node.id === selectedNodeId ? 3 : 2);
    });
  }, [graphData, status, currentNodeId, blocker, selectedNodeId]);

  return <div className="decisionGraph" ref={containerRef} aria-label="LangGraph 决策运行图" />;
}

function TraceNodeDetail({ node, status }: { node: TraceNode; status?: string }) {
  const blocker = describeNodeBlocker(node, status);
  return (
    <section className="traceNodeDetail">
      <h3>{node.label || node.id}</h3>
      {blocker ? <p className="traceBlocker">卡点原因：{blocker}</p> : null}
      <dl>
        <div><dt>节点 ID</dt><dd>{node.id}</dd></div>
        <div><dt>类型</dt><dd>{String(node.kind || "langgraph_node")}</dd></div>
        <div><dt>状态</dt><dd>{statusLabel[String(node.status || "completed")] || String(node.status || "completed")}</dd></div>
        <div><dt>开始</dt><dd>{String(node.started_at || "-")}</dd></div>
        <div><dt>结束</dt><dd>{String(node.ended_at || "-")}</dd></div>
      </dl>
      <div className="traceRefs">
        <div>
          <strong>输入引用</strong>
          <code>{JSON.stringify(node.inputs_ref || [])}</code>
        </div>
        <div>
          <strong>输出引用</strong>
          <code>{JSON.stringify(node.outputs_ref || [])}</code>
        </div>
      </div>
      {node.error ? <p className="traceError">错误：{String(node.error)}</p> : null}
    </section>
  );
}

export function readTraceGraph(trace: unknown): TraceGraph {
  const traceRecord = trace && typeof trace === "object" ? trace as JsonRecord : {};
  const graph = readRecord(traceRecord, "graph");
  const nodes = Array.isArray(graph.nodes)
    ? graph.nodes.filter(isRecord).map((node) => ({
      ...node,
      id: String(node.id || node.step_id || node.name || "node"),
      label: String(node.label || node.name || node.id || "节点")
    }))
    : [];
  const edges = Array.isArray(graph.edges)
    ? graph.edges.filter(isRecord).map((edge) => ({
      ...edge,
      source: String(edge.source || ""),
      target: String(edge.target || ""),
      label: edge.label ? String(edge.label) : "",
      condition: edge.condition ? String(edge.condition) : "",
      taken: Boolean(edge.taken)
    })).filter((edge) => edge.source && edge.target)
    : [];
  if (nodes.length) return { nodes, edges };

  const steps = Array.isArray(traceRecord.steps) ? traceRecord.steps.filter(isRecord) : [];
  const fallbackNodes = steps.map((step, index) => ({
    ...step,
    id: String(step.step_id || step.name || `step-${index + 1}`),
    label: String(step.name || step.step_id || `步骤 ${index + 1}`),
    kind: "trace_step",
    status: String(step.status || "completed")
  }));
  const fallbackEdges = fallbackNodes.slice(0, -1).map((node, index) => ({
    source: node.id,
    target: fallbackNodes[index + 1].id,
    label: "next",
    condition: "next",
    taken: true
  }));
  return { nodes: fallbackNodes, edges: fallbackEdges };
}

function layoutGraphNodes(graphData: TraceGraph, currentNodeId: string, status: string | undefined, blocker: string): FlowNodeView[] {
  const knownCount = graphData.nodes.filter((node) => knownLayout[node.id]).length;
  return graphData.nodes.map((node, index) => {
    const layout = knownLayout[node.id] || {
      x: 290 + (index % 2 === 0 ? 0 : 262),
      y: 24 + Math.floor((knownCount + index) / 2) * 104
    };
    const nodeBlocker = describeNodeBlocker(node, status);
    const rawStatus = String(node.status || "completed");
    const isCurrent = node.id === currentNodeId;
    const tone = nodeBlocker || rawStatus === "failed"
      ? "blocked"
      : isCurrent
        ? (blocker ? "blocked" : "current")
        : rawStatus === "skipped"
          ? "skipped"
          : rawStatus === "pending" || rawStatus === "running"
            ? "pending"
            : "done";

    return {
      node,
      x: layout.x,
      y: layout.y,
      width: layout.width || 230,
      height: layout.height || 68,
      tone,
      statusText: isCurrent ? "当前走到这里" : (statusLabel[rawStatus] || rawStatus),
      note: nodeBlocker || summarizeRefs(node.outputs_ref) || summarizeRefs(node.inputs_ref) || String(node.kind || "")
    };
  });
}

function findCurrentNodeId(graphData: TraceGraph, businessNodeId: string, status?: string) {
  if (businessNodeId && graphData.nodes.some((node) => node.id === businessNodeId)) return businessNodeId;
  const normalizedStatus = String(status || "").toLowerCase();
  if (normalizedStatus.includes("context_request")) return findNode(graphData, "context_gate");
  if (normalizedStatus.includes("action_request")) return findNode(graphData, "action_gate");
  if (normalizedStatus.includes("handoff")) return findNode(graphData, "policy_gate");
  if (normalizedStatus.includes("answer_ready") || normalizedStatus.includes("auto_reply") || normalizedStatus.includes("candidate")) return findNode(graphData, "policy_gate");

  const failed = graphData.nodes.find((node) => String(node.status || "").toLowerCase() === "failed");
  if (failed) return failed.id;
  const running = graphData.nodes.find((node) => ["running", "pending"].includes(String(node.status || "").toLowerCase()));
  if (running) return running.id;
  const takenTargets = graphData.edges.filter((edge) => edge.taken).map((edge) => edge.target);
  const lastTaken = [...takenTargets].reverse().find((id) => graphData.nodes.some((node) => node.id === id && String(node.status || "") !== "skipped"));
  return lastTaken || graphData.nodes[0]?.id || "";
}

function describeBlocker(graphData: TraceGraph, status: string | undefined, currentNodeId: string) {
  const current = graphData.nodes.find((node) => node.id === currentNodeId) || null;
  if (!current) return "";
  return describeNodeBlocker(current, status);
}

function describeNodeBlocker(node: TraceNode, status?: string) {
  if (node.error) return String(node.error);
  const refs = refsArray(node.outputs_ref);
  const contextRequests = refs.filter((item) => item.startsWith("context_request:")).map((item) => item.split(":").slice(1).join(":")).filter(Boolean);
  if (contextRequests.length) return `等待补充上下文：${contextRequests.join("、")}`;

  const normalizedStatus = String(status || "").toLowerCase();
  if (node.id === "action_gate" && normalizedStatus.includes("action_request")) return "等待外部系统确认并回传动作结果";
  if (node.id === "policy_gate" && normalizedStatus.includes("handoff")) return "风险或规则命中，已转人工处理";
  if (String(node.status || "").toLowerCase() === "failed") return "节点执行失败，请查看错误或原始记录";
  return "";
}

function currentProgressText(graphData: TraceGraph, currentNodeId: string) {
  const node = graphData.nodes.find((item) => item.id === currentNodeId);
  if (!node) return "暂无运行节点";
  return `${node.label || node.id}：${statusLabel[String(node.status || "completed")] || String(node.status || "completed")}`;
}

function findNode(graphData: TraceGraph, preferredId: string) {
  return graphData.nodes.find((node) => node.id === preferredId)?.id || graphData.nodes[0]?.id || "";
}

function refsArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function summarizeRefs(value: unknown) {
  const refs = refsArray(value);
  if (!refs.length) return "";
  const compact = refs.slice(0, 2).map((item) => item.replace(/_/g, " "));
  return compact.join(" / ");
}

function inferMissingContext(graphData: TraceGraph) {
  return graphData.nodes.flatMap((node) => refsArray(node.outputs_ref))
    .filter((item) => item.startsWith("context_request:"))
    .map((item) => item.split(":").slice(1).join(":"))
    .filter(Boolean);
}

function businessNodeLabel(nodeId: string, fallback?: string) {
  const labels: Record<string, string> = {
    normalize_request: "请求标准化",
    retrieve_context: "资料检索",
    classify_intent: "意图识别",
    context_gate: "上下文闸门",
    action_gate: "外部操作闸门",
    generate_candidate: "生成建议回复",
    policy_gate: "策略闸门",
    persist_trace: "记录决策路径",
    missing_context: "缺少资料",
    action_request: "等待外部操作",
    handoff: "转人工处理",
    auto_reply: "安全自动回复"
  };
  return labels[nodeId] || fallback || nodeId || "暂无运行节点";
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object";
}
