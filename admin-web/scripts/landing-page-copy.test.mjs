import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../customer-admin/src/App.tsx", import.meta.url), "utf8");
const sharedStyles = readFileSync(new URL("../shared/styles/base.css", import.meta.url), "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}`);
  assert.notEqual(start, -1, `${name} should exist`);
  const nextFunction = source.indexOf("\nfunction ", start + 1);
  return source.slice(start, nextFunction === -1 ? source.length : nextFunction);
}

test("customer landing page uses the approved public narrative", () => {
  const customerSite = extractFunction("CustomerLanding");
  const expectedText = [
    "看得见 AI 怎么回答，也看得见它为什么不回答。",
    "缺资料就先补资料，不让 AI 猜。",
    "客户提问",
    "查商品资料",
    "检查规则与风险",
    "安全回复或转人工",
    "资料有依据",
    "回复有规则",
    "风险可转人工",
    "进入客户后台",
    "查看演示流程"
  ];

  for (const text of expectedText) {
    assert.ok(customerSite.includes(text), `missing landing copy: ${text}`);
  }

  for (const fakePreviewClass of ["previewLine", "previewTable", "previewNav"]) {
    assert.equal(customerSite.includes(fakePreviewClass), false, `fake preview should be removed: ${fakePreviewClass}`);
  }
  assert.ok(customerSite.includes('src="/ai-workflow-proof.png"'), "landing should render the authentic workflow proof");
});

test("customer landing workflow proof is a real, reasonably sized PNG", () => {
  const proofUrl = new URL("../customer-admin/public/ai-workflow-proof.png", import.meta.url);
  assert.ok(existsSync(proofUrl), "authentic workflow proof should exist");
  const proof = readFileSync(proofUrl);
  assert.deepEqual([...proof.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.ok(proof.byteLength > 20_000, "workflow proof should be larger than 20 KB");

  const width = proof.readUInt32BE(16);
  const height = proof.readUInt32BE(20);
  assert.ok(width >= 960, `workflow proof width should remain legible, got ${width}`);
  assert.ok(height >= 540, `workflow proof height should remain legible, got ${height}`);
});

test("customer landing keeps a compact mobile flow and usable tap targets", () => {
  assert.match(sharedStyles, /@media \(max-width: 900px\)[\s\S]*\.landingPage button\s*\{\s*min-height:\s*44px;/);
  assert.match(sharedStyles, /@media \(max-width: 900px\)[\s\S]*\.flowRail li\s*\{[\s\S]*grid-template-columns:\s*28px minmax\(0, 1fr\);/);
  assert.match(sharedStyles, /@media \(max-width: 900px\)[\s\S]*\.reassuranceList article\s*\{[\s\S]*grid-template-columns:\s*28px minmax\(0, 1fr\);/);
});

test("customer site does not expose a system admin entrance", () => {
  const customerSite = extractFunction("CustomerLanding");
  assert.equal(customerSite.includes("系统后台"), false);
  assert.equal(customerSite.includes("system-admin"), false);
  assert.equal(customerSite.includes("/v1/system-admin"), false);
});
