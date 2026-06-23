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
const productContent = customerApp.slice(customerApp.indexOf('function ProductContent'), customerApp.indexOf('function ProductUploadModal'));
const allSource = [customerApp, systemApp, sharedComponents, sharedData].join('\n');

const checks = [
  ['Admin Web regression guard is wired into npm test', packageJson.includes('assert-ui-regressions.mjs')],
  ['Login auth failures render inline form error', loginPanel.includes('loginError') && loginPanel.includes('role="alert"') && styles.includes('.loginError')],
  ['Login 401 auth failures use user-facing credential copy', sharedComponents.includes('message.startsWith("401 ")') && loginPanel.includes('邮箱或密码不正确，请检查后重试。')],
  ['Login auth failures are not shown through global toast', !loginPanel.includes('setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });')],
  ['Login fields are empty by default on live builds', loginPanel.includes('React.useState("")') && !loginPanel.includes('admin@example.test') && !loginPanel.includes('system-admin@example.test') && !loginPanel.includes('React.useState("org-001")')],
  ['Customer login no longer asks for organization ID', !loginPanel.includes('organizationId') && !loginPanel.includes('组织 ID') && !loginPanel.includes('organization_id:')],
  ['Login validates email and password only before requesting auth', loginPanel.includes('请填写邮箱和密码') && !loginPanel.includes('请填写邮箱、密码和组织 ID') && loginPanel.includes('return;')],
  ['Login submits trimmed email without tenant identifiers', loginPanel.includes('onSubmit(email.trim(), password)') && !loginPanel.includes('organization_id:')],
  ['Customer Admin top bar has no manual refresh button or user badge', !topBar.includes('title="刷新"') && !topBar.includes('userBadge')],
  ['Customer workspace hides organization context panel', !customerWorkspace.includes('客户上下文') && !customerWorkspace.includes('label="组织"')],
  ['Customer context selector has no refresh button', !customerWorkspace.includes('onRefresh={refresh}') && !customerWorkspace.includes('刷新</button>')],
  ['Customer overview copy avoids organization wording', !customerOverview.includes('可访问组织') && !customerOverview.includes('ListPanel title="组织"')],
  ['Product content renders a product list and upload CTA', productContent.includes('上传商品') && productContent.includes('DataTable') && productContent.includes('商品列表')],
  ['Product content no longer exposes manual maintenance forms', !productContent.includes('保存商品') && !productContent.includes('登记资产') && !productContent.includes('转换并抽取') && !productContent.includes('保存价格快照')],
  ['DataTable cells expose mobile data labels', sharedComponents.includes('data-label={fieldLabel(field)}') && sharedComponents.includes('data-label="操作"')],
  ['Field label map avoids organization wording for customer-facing tables', sharedData.includes('organization_id: "客户 ID"') && !allSource.includes('organization_id: "组织 ID"')],
  ['Status badges render localized status text', sharedData.includes('const statusLabel') && sharedData.includes('title={value}>{statusLabel[value] || value}</span>')],
  ['EmptyState accepts title, description, and optional action', sharedComponents.includes('function EmptyState({ title, description, action }: EmptyStateProps)')],
  ['Mobile table cells render labels before content', styles.includes('td::before') && styles.includes('content: attr(data-label)')],
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
