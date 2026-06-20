import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const adminRoot = path.resolve(scriptDir, '..');
const root = path.resolve(adminRoot, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const main = read('admin-web/src/main.tsx');
const styles = read('admin-web/src/styles.css');
const readme = read('README.md');
const agents = read('AGENTS.md');
const customerDesign = read('docs/customer-admin-design.md');
const systemDesign = read('docs/system-admin-design.md');

const checks = [
  ['README routes to normalized Admin UI sources', readme.includes('Admin UI 实现基准') && readme.includes('README 只保留设计入口')],
  ['AGENTS records system prototype as implementation baseline', agents.includes('System Admin implementation baseline') && agents.includes('docs/system-admin-ui-prototype.html')],
  ['Customer Admin design records implementation baseline', customerDesign.includes('### 3.1 客户后台实现基准') && customerDesign.includes('不得展示“系统后台”按钮、tab、workspace switch')],
  ['System Admin design records normalized prototype baseline', systemDesign.includes('### 5.0 当前实现基准') && systemDesign.includes('系统后台 UI 的源文档是本文')],
  ['App routes by host/path instead of a shared workspace switch', main.includes('resolveAdminSurface') && !main.includes('workspaceSwitch')],
  ['System Admin routes are gated away from customer Admin hosts', main.includes('isSystemAdminRouteAllowed') && !main.includes('if (path === "/system-admin") return "system-admin";')],
  ['Customer shell has no system-admin switch or system auth probe', !main.includes('setWorkspace("system")') && !main.includes('refreshSession("system")')],
  ['System navigation matches prototype required pages', ['配置完成度', '资料与知识', '规则与动作', '评测与发布'].every((label) => main.includes(label))],
  ['Carbon topbar and shell classes are present', main.includes('systemTopbar') && main.includes('systemContextPanel')],
  ['Tables expose responsive data labels', main.includes('data-label') && styles.includes('td::before')],
  ['UI regression guard is wired into npm test', read('admin-web/package.json').includes('assert-ui-regressions.mjs')]
];

const failures = checks.filter(([, ok]) => !ok);
if (failures.length) {
  console.error('Admin UI regression guard failed:');
  for (const [name] of failures) console.error(`- ${name}`);
  process.exit(1);
}
console.log(`Admin UI regression guard passed (${checks.length} checks).`);
