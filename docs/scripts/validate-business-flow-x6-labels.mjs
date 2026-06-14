import { readFileSync } from 'node:fs';

const html = readFileSync('docs/system-architecture.html', 'utf8');
const initMatch = html.match(/function initBusinessFlowDiagram\(\) \{[\s\S]*?\n    \}\n\n    function renderQuickStartContent/);

if (!initMatch) {
  throw new Error('initBusinessFlowDiagram function not found');
}

const initSource = initMatch[0];
const failures = [];

function expect(condition, message) {
  if (!condition) failures.push(message);
}

function extractNumber(name) {
  const match = initSource.match(new RegExp(`const ${name} = ([0-9]+);`));
  if (!match) throw new Error(`missing const ${name}`);
  return Number(match[1]);
}

function extractNode(id) {
  const match = initSource.match(new RegExp(`id: '${id}',[\\s\\S]*?x: ([^,]+),\\n\\s*y: ([0-9]+),[\\s\\S]*?width: ([^,]+),\\n\\s*height: ([0-9]+)`));
  if (!match) throw new Error(`missing node ${id}`);
  return {
    id,
    xExpr: match[1].trim(),
    y: Number(match[2]),
    widthExpr: match[3].trim(),
    height: Number(match[4])
  };
}

function extractArray(name) {
  const marker = `const ${name} = `;
  const start = initSource.indexOf(marker);
  if (start < 0) throw new Error(`${name} declaration not found`);
  const arrayStart = initSource.indexOf('[', start);
  let depth = 0;
  for (let index = arrayStart; index < initSource.length; index += 1) {
    const char = initSource[index];
    if (char === '[') depth += 1;
    if (char === ']') depth -= 1;
    if (depth === 0) {
      return Function(`return (${initSource.slice(arrayStart, index + 1)})`)();
    }
  }
  throw new Error(`${name} array end not found`);
}

expect(!html.includes('.x6-flow-label-layer'), 'DOM label layer CSS must be removed');
expect(!html.includes('.x6-flow-label'), 'DOM label CSS must be removed');
expect(!initSource.includes('labelLayer'), 'DOM labelLayer code must be removed');
expect(!initSource.includes('updateFlowLabels'), 'DOM label update function must be removed');
expect(initSource.includes("Graph.registerNode('business-flow-label'"), 'business-flow-label node type must be registered');
expect(initSource.includes("role: 'edge-label'"), 'edge label nodes must use data.role = edge-label');
expect(!initSource.includes("return Boolean(cell && (cell.getData() || {}).role === 'edge-label')"), 'edge label nodes must not be movable');
expect(initSource.includes("edgeLabels.forEach"), 'edge label nodes must be created from edgeLabels');
expect(initSource.includes("addFlowSegment"), 'flow edges must be split into labeled segments');
expect(initSource.includes("`${edge.id}-source-label`"), 'source-to-label edge segment must be created');
expect(initSource.includes("`${edge.id}-label-target`"), 'label-to-target edge segment must be created');
expect(!initSource.includes("router: { name: 'manhattan'"), 'flow label segments must not use manhattan routing');
expect(!initSource.includes("connector: { name: 'rounded'"), 'flow label segments must not use rounded multi-bend connector');
expect(initSource.includes("connector: { name: 'normal'"), 'flow label segments must use straight normal connector');
expect(initSource.includes("anchor: { name: 'center' }"), 'flow label segments must connect through center anchors');
expect(!initSource.includes('oppositeAnchor(edge.'), 'flow label segments must not choose edge-side anchors for label nodes');
expect(!initSource.includes("id: 'realtime'"), 'realtime notification must not be a flow diagram node');
expect(!initSource.includes("edge-agent-realtime"), 'realtime notification must not be a flow diagram edge');
expect(!initSource.includes("label-agent-realtime"), 'realtime notification must not be a flow diagram edge label');
expect(html.includes('实时通知（非本期目标）'), 'documentation must keep realtime notification marked as not in current scope');
expect(html.includes('WebSocket(实时连接) 是后续异步通知能力'), 'documentation must explain WebSocket realtime notification as future async capability');

const flowEdges = extractArray('flowEdges');
const edgeLabelIds = [...initSource.matchAll(/labelId: '([^']+)'/g)].map(match => match[1]);
expect(edgeLabelIds.length === flowEdges.length, `expected ${flowEdges.length} edge label ids, found ${edgeLabelIds.length}`);
expect(new Set(edgeLabelIds).size === edgeLabelIds.length, 'edge label ids must be unique');

const flowEdgeById = Object.fromEntries(flowEdges.map(edge => [edge.id, edge]));
expect(flowEdges.length === 8, `expected 8 business flow edges after removing realtime node, found ${flowEdges.length}`);
expect((flowEdgeById['edge-workbench-business']?.offsetX || 0) <= -48, 'workbench/business API label must be shifted left to spread branch labels');
expect((flowEdgeById['edge-workbench-feedback']?.offsetY || 0) >= 48, 'workbench/feedback API label must be shifted down to spread branch labels');
expect((flowEdgeById['edge-workbench-trace']?.offsetX || 0) >= 48, 'workbench/trace API label must be shifted right to spread branch labels');

const framePadding = extractNumber('framePadding');
const nodes = ['platform', 'cs', 'request', 'agent', 'response', 'workbench', 'business', 'feedback', 'trace'].map(extractNode);
const byId = Object.fromEntries(nodes.map(node => [node.id, node]));
const frameMembers = {
  request: ['platform', 'cs', 'request'],
  agent: ['agent', 'response'],
  action: ['workbench', 'business', 'feedback', 'trace']
};

function yBox(ids) {
  return {
    top: Math.min(...ids.map(id => byId[id].y)) - framePadding,
    bottom: Math.max(...ids.map(id => byId[id].y + byId[id].height)) + framePadding
  };
}

const request = yBox(frameMembers.request);
const agent = yBox(frameMembers.agent);
const action = yBox(frameMembers.action);
const gapRequestAgent = agent.top - request.bottom;
const gapAgentAction = action.top - agent.bottom;
expect(gapRequestAgent >= 112, `request/agent frame gap ${gapRequestAgent}px < 112px`);
expect(gapAgentAction >= 112, `agent/action frame gap ${gapAgentAction}px < 112px`);
expect(byId.business.y >= 1600, `business branch y ${byId.business.y}px < 1600px`);
expect(byId.feedback.y >= 1600, `feedback branch y ${byId.feedback.y}px < 1600px`);
expect(byId.trace.y >= 1600, `trace branch y ${byId.trace.y}px < 1600px`);

const cssHeight = Number(html.match(/\.api-business-flow-diagram \{[\s\S]*?height: ([0-9]+)px;/)?.[1]);
expect(cssHeight >= 1840, `diagram CSS height ${cssHeight}px < 1840px`);

if (failures.length) {
  console.error(failures.join('\n'));
  process.exit(1);
}

console.log(JSON.stringify({
  flowEdges: flowEdges.length,
  edgeLabelIds: edgeLabelIds.length,
  gapRequestAgent,
  gapAgentAction,
  cssHeight
}, null, 2));
