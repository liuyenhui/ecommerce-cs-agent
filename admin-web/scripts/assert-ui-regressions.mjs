import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const main = readFileSync(join(root, "src", "main.tsx"), "utf8");
const styles = readFileSync(join(root, "src", "styles.css"), "utf8");

const checks = [
  {
    name: "DataTable cells expose mobile data-labels",
    pass: /<td key=\{field\} data-label=\{fieldLabel\(field\)\}>/.test(main)
  },
  {
    name: "field label map includes organization_id",
    pass: /organization_id:\s*"组织 ID"/.test(main)
  },
  {
    name: "status badges render localized status text",
    pass: /const statusLabel/.test(main) && /title=\{value\}/.test(main)
  },
  {
    name: "EmptyState accepts title, description, and optional action",
    pass: /function EmptyState\(\{ title, description, action \}/.test(main)
  },
  {
    name: "mobile cells render labels with CSS before content",
    pass: /td::before/.test(styles) && /content:\s*attr\(data-label\)/.test(styles)
  }
];

const failed = checks.filter((check) => !check.pass);

if (failed.length > 0) {
  for (const check of failed) {
    console.error(`FAIL ${check.name}`);
  }
  process.exit(1);
}

for (const check of checks) {
  console.log(`PASS ${check.name}`);
}
