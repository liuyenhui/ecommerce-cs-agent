import { readFileSync } from 'node:fs';

const html = readFileSync('docs/system-architecture.html', 'utf8');
const failures = [];

function expect(condition, message) {
  if (!condition) failures.push(message);
}

const mainScript = html.match(/<script>\n([\s\S]*?)\n  <\/script>/)?.[1] || '';
const renderViewSource = mainScript.match(/function renderView\(key\) \{[\s\S]*?\n    \}/)?.[0] || '';
const diagramCss = html.match(/#diagram \{[\s\S]*?\n    \}/)?.[0] || '';

expect(html.includes('<script src="vendor/x6.min.js"></script>'), 'page must load local AntV X6 runtime');
expect(!html.includes('<script src="vendor/go.js"></script>'), 'page must not load GoJS runtime');
expect(!/\bgo\./.test(html), 'HTML runtime must not reference go.* APIs');
expect(!html.includes('GraphLinksModel'), 'HTML runtime must not use GoJS GraphLinksModel');
expect(!html.includes('GraphObject.make'), 'HTML runtime must not use GoJS GraphObject.make');
expect(!html.includes('GoJS minimal sample'), 'page copy must not describe the runtime as GoJS');
expect(diagramCss.includes('position: relative;'), 'main X6 diagram container must be position: relative');
expect(diagramCss.includes('overflow: hidden;'), 'main X6 diagram container must hide overflow');
expect(diagramCss.includes('touch-action: none;'), 'main X6 diagram container must disable browser touch gestures');

expect(mainScript.includes("Graph.registerNode('architecture-flow-node'"), 'main architecture X6 node type must be registered');
expect(mainScript.includes("Graph.registerNode('architecture-flow-label'"), 'main architecture X6 edge-label node type must be registered');
expect(mainScript.includes('function createArchitectureGraph'), 'main architecture graph factory must exist');
expect(mainScript.includes('function renderArchitectureViewX6'), 'main architecture views must render through X6');
expect(mainScript.includes("`${edge.id}-source-label`"), 'labeled architecture edges must split source to label');
expect(mainScript.includes("`${edge.id}-label-target`"), 'labeled architecture edges must split label to target');
expect(mainScript.includes("role: 'edge-label'"), 'architecture edge labels must be X6 read-only nodes');
expect(mainScript.includes('nodeMovable: isArchitectureFlowNode'), 'only architecture component nodes should be movable');

expect(renderViewSource.includes('renderArchitectureViewX6(key)'), 'renderView must delegate to X6 renderer');
expect(!renderViewSource.includes('diagram.model'), 'renderView must not assign a GoJS model');
expect(!renderViewSource.includes('layoutFor'), 'renderView must not use GoJS layouts');

if (failures.length) {
  console.error(failures.join('\n'));
  process.exit(1);
}

console.log(JSON.stringify({
  x6Runtime: true,
  goRuntimeRemoved: true,
  mainRenderer: 'AntV X6'
}, null, 2));
