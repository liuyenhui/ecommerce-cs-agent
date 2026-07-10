import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const adminRoot = path.resolve(scriptDir, '..');
const root = path.resolve(adminRoot, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const customerApp = read('admin-web/customer-admin/src/App.tsx');
const systemApp = read('admin-web/system-admin/src/App.tsx');
const sharedComponents = read('admin-web/shared/components.tsx');
const sharedData = read('admin-web/shared/data.tsx');
const sharedTraceReplay = read('admin-web/shared/trace-replay.tsx');
const styles = [
  read('admin-web/shared/styles/base.css'),
  read('admin-web/customer-admin/src/styles.css'),
  read('admin-web/system-admin/src/styles.css')
].join('\n');
const packageJson = read('admin-web/package.json');
const nginxConf = read('admin-web/nginx.conf');
const loginPanel = sharedComponents.slice(sharedComponents.indexOf('function LoginPanelBase'), sharedComponents.indexOf('function loginFailureMessage'));
const topBar = sharedComponents.slice(sharedComponents.indexOf('function TopBar'), sharedComponents.indexOf('function LoginPanelBase'));
const customerWorkspace = customerApp.slice(customerApp.indexOf('function CustomerWorkspace'), customerApp.indexOf('function CustomerOverview'));
const customerOverview = customerApp.slice(customerApp.indexOf('function CustomerOverview'), customerApp.indexOf('function ProductContent'));
const messageHistory = customerApp.slice(customerApp.indexOf('function MessageHistory'), customerApp.indexOf('function MessageTraceDrawer'));
const customerLanding = customerApp.slice(customerApp.indexOf('function CustomerLanding'), customerApp.indexOf('function CustomerAdminShell'));
const productContent = customerApp.slice(customerApp.indexOf('function ProductContent'), customerApp.indexOf('function ProductUploadModal'));
const allSource = [customerApp, systemApp, sharedComponents, sharedData, sharedTraceReplay].join('\n');

const checks = [
  ['Customer landing uses authentic workflow proof instead of fake skeleton art', customerLanding.includes('/ai-workflow-proof.png') && !customerLanding.includes('previewLine') && !customerLanding.includes('previewTable') && !customerLanding.includes('previewNav')],
  ['Customer landing tells the approved four-step workflow story', ['客户提问', '查商品资料', '检查规则与风险', '安全回复或转人工'].every((copy) => customerLanding.includes(copy))],
  ['Admin Web regression guard is wired into npm test', packageJson.includes('assert-ui-regressions.mjs')],
  ['Login auth failures render inline form error', loginPanel.includes('loginError') && loginPanel.includes('role="alert"') && styles.includes('.loginError')],
  ['Login 401 auth failures use user-facing credential copy', sharedComponents.includes('message.startsWith("401 ")') && loginPanel.includes('邮箱或密码错误')],
  ['Customer login renders open_erp_agent WeChat bridge entry only in customer wrapper', customerApp.includes('使用 open_erp_agent 微信登录') && customerApp.includes('https://www.fcihome.com/ai-cs/customer-admin-login') && !systemApp.includes('open_erp_agent 微信')],
  ['Customer login maps distinct OIDC failure query errors', customerApp.includes('oidc_unbound_account') && customerApp.includes('OIDC 未绑定账号') && customerApp.includes('oidc_disabled') && customerApp.includes('OIDC 配置未启用') && customerApp.includes('oidc_state_pkce_failed') && customerApp.includes('state/PKCE 校验失败')],
  ['Login auth failures are not shown through global toast', !loginPanel.includes('setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });')],
  ['Login fields are empty by default on live builds', loginPanel.includes('React.useState("")') && !loginPanel.includes('admin@example.test') && !loginPanel.includes('system-admin@example.test') && !loginPanel.includes('React.useState("org-001")')],
  ['Customer login no longer asks for organization ID', !loginPanel.includes('organizationId') && !loginPanel.includes('组织 ID') && !loginPanel.includes('organization_id:')],
  ['Login validates email and password only before requesting auth', loginPanel.includes('请填写邮箱和密码') && !loginPanel.includes('请填写邮箱、密码和组织 ID') && loginPanel.includes('return;')],
  ['Login submits trimmed email without tenant identifiers', loginPanel.includes('onSubmit(email.trim(), password)') && !loginPanel.includes('organization_id:')],
  ['Customer Admin top bar has no manual refresh button or user badge', !topBar.includes('title="刷新"') && !topBar.includes('userBadge')],
  ['Customer workspace hides organization context panel', !customerWorkspace.includes('客户上下文') && !customerWorkspace.includes('label="组织"')],
  ['Customer context selector has no refresh button', !customerWorkspace.includes('onRefresh={refresh}') && !customerWorkspace.includes('刷新</button>')],
  ['Customer overview copy avoids organization wording', !customerOverview.includes('可访问组织') && !customerOverview.includes('ListPanel title="组织"')],
  ['Customer message history renders conversation workspace instead of table', messageHistory.includes('messageHistoryWorkspace') && messageHistory.includes('conversationList') && messageHistory.includes('conversationTimeline') && !messageHistory.includes('<DataTable')],
  ['Customer message history has no status filters or read-state labels', !messageHistory.includes('待回复') && !messageHistory.includes('含订单') && !messageHistory.includes('本地历史') && !messageHistory.includes('客户已读') && !messageHistory.includes('已读/状态')],
  ['Customer decision graph loads X6 lazily to keep the initial bundle below warning size', !allSource.includes('from "@antv/x6"') && sharedTraceReplay.includes('import("@antv/x6")')],
  ['Customer decision graph renders runtime trace.graph instead of fixed eight-step placeholder', customerApp.includes('DecisionTraceReplay') && sharedTraceReplay.includes('readTraceGraph') && sharedTraceReplay.includes('graphData.nodes') && sharedTraceReplay.includes('edge.taken') && !sharedTraceReplay.includes('接收消息", "字段映射"')],
  ['Decision graph uses architecture-style X6 nodes with right-angle routes and flowing taken edges', sharedTraceReplay.includes('Graph.registerNode("decision-flow-node"') && sharedTraceReplay.includes('shape: "decision-flow-node"') && sharedTraceReplay.includes('router: { name: "manhattan"') && sharedTraceReplay.includes('class: edge.taken ? "trace-flow-edge active" : "trace-flow-edge inactive"')],
  ['Decision graph highlights business progress and blocker reasons', sharedTraceReplay.includes('findCurrentNodeId') && sharedTraceReplay.includes('describeBlocker') && sharedTraceReplay.includes('presentation.title') && sharedTraceReplay.includes('presentation.explanation') && sharedTraceReplay.includes('当前：')],
  ['Decision replay consumes the pure business presenter and accepts raw workflow values', sharedTraceReplay.includes('presentDecisionTrace') && sharedTraceReplay.includes('action?: unknown') && sharedTraceReplay.includes('risk?: unknown') && sharedTraceReplay.includes('missingContext?: unknown')],
  ['Decision replay infers missing context from graph refs when the summary omits it', sharedTraceReplay.includes('inferMissingContext(graphData)') && sharedTraceReplay.includes('context_request:')],
  ['Decision replay keeps raw workflow metadata under technical details', sharedTraceReplay.includes('<details className="traceTechnicalDetails">') && sharedTraceReplay.includes('<summary>技术详情</summary>') && sharedTraceReplay.includes('thread_id:') && sharedTraceReplay.includes('graph_version:')],
  ['Decision replay exposes an X6 failure fallback while retaining the timeline', sharedTraceReplay.includes('流程图暂时无法显示，请查看下方节点时间线。') && sharedTraceReplay.includes('dispatchGraphUi({ type: "failed" })') && sharedTraceReplay.includes('aria-label="节点时间线"')],
  ['Decision replay recovers from X6 failures without rebuilding on node selection', sharedTraceReplay.includes('const graphRef = React.useRef<any>(null)') && sharedTraceReplay.includes('const handleGraphAvailable = React.useCallback') && sharedTraceReplay.includes('graphRef.current?.getCellById') && !sharedTraceReplay.includes('}, [graphData, status, selectedNodeId, currentNodeId, blocker')],
  ['Decision replay applies latest selection after lazy import resolves', sharedTraceReplay.includes('latestSelectionRef') && sharedTraceReplay.includes('applySelectedNodeStyles')],
  ['Decision graph failure hides the canvas and offers retry before the timeline', sharedTraceReplay.includes('hidden={graphUnavailable}') && sharedTraceReplay.includes('重试流程图') && sharedTraceReplay.includes('retryKey') && sharedTraceReplay.indexOf('重试流程图') < sharedTraceReplay.indexOf('aria-label="节点时间线"')],
  ['Decision graph failure disposes partial graph state', sharedTraceReplay.includes('graph?.dispose()') && sharedTraceReplay.includes('graphRef.current = null')],
  ['Node detail keeps technical fields collapsed and never renders raw node errors', sharedTraceReplay.includes('<details className="traceNodeTechnicalDetails">') && sharedTraceReplay.includes('<summary>技术详情</summary>') && !sharedTraceReplay.includes('错误：{String(node.error)}')],
  ['Decision graph node subtitles use fixed business copy instead of raw refs', sharedTraceReplay.includes('businessNodeNote(node.id') && !sharedTraceReplay.includes('summarizeRefs(node.outputs_ref)') && !sharedTraceReplay.includes('summarizeRefs(node.inputs_ref)')],
  ['Customer styles do not duplicate shared drawer and graph rules', !read('admin-web/customer-admin/src/styles.css').includes('.messageTraceDrawer') && !read('admin-web/customer-admin/src/styles.css').includes('.decisionGraph')],
  ['System Admin decision trace detail fetches per-decision replay and renders the shared graph', systemApp.includes('/v1/system-admin/message-traces/${decisionId}') && systemApp.includes('DecisionTraceReplay') && systemApp.includes('traceDetail')],
  ['Product content renders a product list and upload CTA', productContent.includes('上传商品') && productContent.includes('DataTable') && productContent.includes('商品列表')],
  ['Product content no longer exposes manual maintenance forms', !productContent.includes('保存商品') && !productContent.includes('登记资产') && !productContent.includes('转换并抽取') && !productContent.includes('保存价格快照')],
  ['DataTable cells expose mobile data labels', sharedComponents.includes('data-label={fieldLabel(field)}') && sharedComponents.includes('data-label="操作"')],
  ['Field label map avoids organization wording for customer-facing tables', sharedData.includes('organization_id: "客户 ID"') && !allSource.includes('organization_id: "组织 ID"')],
  ['Status badges render localized status text', sharedData.includes('const statusLabel') && sharedData.includes('title={value}>{statusLabel[value] || value}</span>')],
  ['EmptyState accepts title, description, and optional action', sharedComponents.includes('function EmptyState({ title, description, action }: EmptyStateProps)')],
  ['Mobile table cells render labels before content', styles.includes('td::before') && styles.includes('content: attr(data-label)')],
  ['Nginx host map has enough bucket size for dev admin hostnames', /map_hash_bucket_size\s+128;/.test(nginxConf)],
  ['Nginx does not serve index.html for missing hashed assets', /location\s+\^~\s+\/assets\/\s*\{[\s\S]*try_files\s+\/\$admin_site\$uri\s+=404;/.test(nginxConf)],
  ['Nginx keeps SPA documents revalidatable after deployments', /location\s+=\s+\/index\.html\s*\{[\s\S]*Cache-Control[\s\S]*no-store/.test(nginxConf)]
];

const failures = checks.filter(([, ok]) => !ok);
if (failures.length) {
  console.error('Admin UI regression guard failed:');
  for (const [name] of failures) console.error(`- ${name}`);
  process.exit(1);
}
console.log(`Admin UI regression guard passed (${checks.length} checks).`);
