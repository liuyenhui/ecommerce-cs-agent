import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../customer-admin/src/App.tsx", import.meta.url), "utf8");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}`);
  assert.notEqual(start, -1, `${name} should exist`);
  const nextFunction = source.indexOf("\nfunction ", start + 1);
  return source.slice(start, nextFunction === -1 ? source.length : nextFunction);
}

test("customer landing page uses the approved public narrative", () => {
  const customerSite = extractFunction("CustomerLanding");
  const expectedText = [
    "商品信息管好了，AI 客服才答得准。",
    "上传商品说明书、价格和常见问题，让 AI 先学习，再通过模拟问答检查效果。真正自动回复前，还能用规则控制范围和风险。",
    "商品信息统一管理",
    "AI 自动学习商品知识",
    "AI 客服回复可控",
    "上传商品说明书",
    "AI 学习",
    "模拟问答",
    "AI 自动回复",
    "进入客户后台",
    "查看演示流程",
    "客户登录",
    "先管好商品资料，再让 AI 自动回复。"
  ];

  for (const text of expectedText) {
    assert.ok(customerSite.includes(text), `missing landing copy: ${text}`);
  }
});

test("customer site does not expose a system admin entrance", () => {
  const customerSite = extractFunction("CustomerLanding");
  assert.equal(customerSite.includes("系统后台"), false);
  assert.equal(customerSite.includes("system-admin"), false);
  assert.equal(customerSite.includes("/v1/system-admin"), false);
});
