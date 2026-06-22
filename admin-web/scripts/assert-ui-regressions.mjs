import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const adminRoot = path.resolve(scriptDir, '..');
const root = path.resolve(adminRoot, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const main = read('admin-web/src/main.tsx');
const styles = read('admin-web/src/styles.css');
const packageJson = read('admin-web/package.json');
const loginPanel = main.slice(main.indexOf('function LoginPanel'), main.indexOf('function CustomerWorkspace'));

const checks = [
  ['Admin Web regression guard is wired into npm test', packageJson.includes('assert-ui-regressions.mjs')],
  ['Login auth failures render inline form error', loginPanel.includes('loginError') && loginPanel.includes('role="alert"') && styles.includes('.loginError')],
  ['Login 401 auth failures use user-facing credential copy', main.includes('message.startsWith("401 ")') && loginPanel.includes('邮箱或密码不正确，请检查后重试。')],
  ['Login auth failures are not shown through global toast', !loginPanel.includes('setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });')]
];

const failures = checks.filter(([, ok]) => !ok);
if (failures.length) {
  console.error('Admin UI regression guard failed:');
  for (const [name] of failures) console.error(`- ${name}`);
  process.exit(1);
}
console.log(`Admin UI regression guard passed (${checks.length} checks).`);
