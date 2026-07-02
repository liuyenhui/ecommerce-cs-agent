import React from "react";
import { readRecord } from "./data";
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

export function DecisionTraceReplay({ trace, status }: { trace: unknown; status?: string }) {
  const graphData = readTraceGraph(trace);
  const [selectedNodeId, setSelectedNodeId] = React.useState(() => graphData.nodes[0]?.id || "");
  const selectedNode = graphData.nodes.find((node) => node.id === selectedNodeId) || graphData.nodes[0] || null;

  React.useEffect(() => {
    if (!graphData.nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(graphData.nodes[0]?.id || "");
    }
  }, [graphData.nodes, selectedNodeId]);

  return (
    <section className="traceReplay" aria-label="LangGraph 单条消息运行回放">
      <div className="traceReplayMeta">
        <span>thread_id: {String(readRecord(trace, "graph").thread_id || readRecord(trace, "trace").thread_id || (trace as JsonRecord | undefined)?.thread_id || "-")}</span>
        <span>graph_version: {String((trace as JsonRecord | undefined)?.graph_version || "-")}</span>
        <span>status: {status || "-"}</span>
      </div>
      <DecisionFlowGraph graphData={graphData} selectedNodeId={selectedNode?.id || ""} onSelect={setSelectedNodeId} />
      <ol className="traceTimeline" aria-label="节点时间线">
        {graphData.nodes.map((node) => (
          <li key={node.id} className={node.id === selectedNode?.id ? "active" : ""}>
            <button type="button" onClick={() => setSelectedNodeId(node.id)}>
              <strong>{node.label || node.id}</strong>
              <span>{node.status || "completed"}</span>
            </button>
          </li>
        ))}
      </ol>
      {selectedNode ? <TraceNodeDetail node={selectedNode} /> : <p className="emptyText">暂无可回放节点</p>}
    </section>
  );
}

function DecisionFlowGraph({
  graphData,
  selectedNodeId,
  onSelect
}: {
  graphData: TraceGraph;
  selectedNodeId: string;
  onSelect: (nodeId: string) => void;
}) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!containerRef.current) return undefined;
    let disposed = false;
    let graph: any = null;

    void import("@antv/x6").then(({ Graph }) => {
      if (disposed || !containerRef.current) return;
      const width = containerRef.current.clientWidth || 640;
      graph = new Graph({
        container: containerRef.current,
        width,
        height: 360,
        interacting: false,
        panning: false,
        mousewheel: false,
        background: { color: "#ffffff" }
      });
      const activeGraph = graph;
      const nodeRefs = new Map<string, any>();
      graphData.nodes.forEach((node, index) => {
        const status = String(node.status || "completed");
        const fill = node.id === selectedNodeId ? "#dbeafe" : status === "failed" ? "#fee2e2" : "#eef2ff";
        const ref = activeGraph.addNode({
          id: node.id,
          x: 26 + (index % 2) * 260,
          y: 24 + Math.floor(index / 2) * 76,
          width: 210,
          height: 48,
          label: `${node.label || node.id}\n${status}`,
          attrs: {
            body: { rx: 6, ry: 6, stroke: node.id === selectedNodeId ? "#2563eb" : "#94a3b8", strokeWidth: node.id === selectedNodeId ? 2 : 1, fill },
            label: { fill: "#1f2937", fontSize: 12, fontWeight: 650, lineHeight: 16 }
          }
        });
        if (ref) nodeRefs.set(node.id, ref);
      });
      graphData.edges.forEach((edge) => {
        const source = nodeRefs.get(edge.source);
        const target = nodeRefs.get(edge.target);
        if (!source || !target) return;
        activeGraph.addEdge({
          source,
          target,
          labels: edge.label ? [{ attrs: { label: { text: edge.label, fontSize: 11, fill: edge.taken ? "#0f172a" : "#94a3b8" } } }] : undefined,
          attrs: {
            line: {
              stroke: edge.taken ? "#2563eb" : "#cbd5e1",
              strokeWidth: edge.taken ? 1.8 : 1,
              strokeDasharray: edge.taken ? "" : "5 5",
              targetMarker: "block"
            }
          },
          router: { name: "manhattan" }
        });
      });
      activeGraph.on("node:click", ({ node }: { node?: { id?: string } }) => {
        if (node?.id) onSelect(String(node.id));
      });
      activeGraph.centerContent();
    });
    return () => {
      disposed = true;
      graph?.dispose();
    };
  }, [graphData, selectedNodeId, onSelect]);

  return <div className="decisionGraph" ref={containerRef} aria-label="LangGraph 决策运行图" />;
}

function TraceNodeDetail({ node }: { node: TraceNode }) {
  return (
    <section className="traceNodeDetail">
      <h3>{node.label || node.id}</h3>
      <dl>
        <div><dt>节点 ID</dt><dd>{node.id}</dd></div>
        <div><dt>类型</dt><dd>{String(node.kind || "langgraph_node")}</dd></div>
        <div><dt>状态</dt><dd>{String(node.status || "completed")}</dd></div>
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

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object";
}
