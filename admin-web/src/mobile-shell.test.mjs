import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

const customerSource = readFileSync(new URL("../customer-admin/src/App.tsx", import.meta.url), "utf8");
const systemSource = readFileSync(new URL("../system-admin/src/App.tsx", import.meta.url), "utf8");
const sharedSource = readFileSync(new URL("../shared/components.tsx", import.meta.url), "utf8");
const cssSource = readFileSync(new URL("../shared/styles/base.css", import.meta.url), "utf8");
const llmSource = readFileSync(new URL("../system-admin/src/pages/LlmGovernancePage.tsx", import.meta.url), "utf8");
const releasesSource = readFileSync(new URL("../system-admin/src/pages/ReleasesPage.tsx", import.meta.url), "utf8");

test("unauthenticated admin pages render the login task without the backend rail", () => {
  assert.match(customerSource, /function CustomerAdminShell\(/);
  assert.match(systemSource, /export function App\(/);
  assert.match(customerSource, /const isAuthenticated = Boolean\(customerSession\)/);
  assert.match(systemSource, /const isAuthenticated = Boolean\(systemSession\)/);
  assert.match(sharedSource, /className=\{`appShell \$\{isAuthenticated \? "isAuthed" : "isGuest"\}/);
  assert.match(sharedSource, /\{isAuthenticated \? \(\s*<aside className="rail"/);
  assert.match(cssSource, /\.appShell\.isGuest\s*\{[\s\S]*grid-template-columns:\s*1fr;/);
});

test("authenticated mobile navigation is a collapsible drawer with usable tap targets", () => {
  assert.match(sharedSource, /className="mobileNavButton"/);
  assert.match(customerSource, /onToggleNav=\{\(\) => setMobileNavOpen\(\(open\) => !open\)\}/);
  assert.match(sharedSource, /onNavigate\?: \(\) => void/);
  assert.match(sharedSource, /onNavigate\?\.\(\)/);
  assert.match(cssSource, /\.appShell\.navOpen \.rail\s*\{[\s\S]*transform:\s*translateX\(0\);/);
  assert.match(cssSource, /@media \(max-width: 900px\)[\s\S]*\.rail\s*\{[\s\S]*position:\s*fixed;[\s\S]*transform:\s*translateX\(-100%\);/);
  assert.match(cssSource, /@media \(max-width: 900px\)[\s\S]*button\s*\{[\s\S]*min-height:\s*44px;/);
});

test("trace node badges wrap on mobile without horizontal scrolling or full-width items", () => {
  assert.match(cssSource, /@media \(max-width: 900px\)[\s\S]*\.traceNodeBadges\s*\{[\s\S]*display:\s*flex;[\s\S]*flex-wrap:\s*wrap;[\s\S]*width:\s*100%;[\s\S]*overflow-x:\s*hidden;/);
  assert.doesNotMatch(cssSource, /@media \(max-width: 900px\)[\s\S]*\.traceNodeBadges li\s*\{[\s\S]*width:\s*100%;/);
});

test("desktop collapsed navigation stays accessible and exactly 64 pixels wide", () => {
  assert.match(cssSource, /\.appShell\.railCollapsed:not\(\.isGuest\)\s*\{[\s\S]*grid-template-columns:\s*64px minmax\(0, 1fr\);/);
  assert.match(sharedSource, /className="railCollapseButton"[\s\S]*aria-label=\{railCollapsed \? "展开桌面导航" : "收起桌面导航"\}/);
  assert.match(sharedSource, /aria-expanded=\{!railCollapsed\}/);
  assert.match(sharedSource, /title=\{railCollapsed \? "展开导航" : "收起导航"\}/);
  assert.match(sharedSource, /title=\{showTooltips \? item\.label : undefined\}/);
  assert.match(cssSource, /button:focus-visible,[\s\S]*input:focus-visible,[\s\S]*select:focus-visible,[\s\S]*textarea:focus-visible/);
});

test("mobile drawer retains modal focus management and closes after navigation", () => {
  assert.match(sharedSource, /role=\{mobileModal \? "dialog" : undefined\}/);
  assert.match(sharedSource, /aria-modal=\{mobileModal \? "true" : undefined\}/);
  assert.match(sharedSource, /mainPane\.setAttribute\("inert", ""\)/);
  assert.match(sharedSource, /if \(event\.key === "Escape"\)[\s\S]*onCloseNav\(\)/);
  assert.match(sharedSource, /event\.shiftKey[\s\S]*last\.focus\(\)/);
  assert.match(sharedSource, /restoreFocusRef\.current\.focus\(\)/);
  assert.match(sharedSource, /onNavigate\?\.\(\)/);
  assert.match(systemSource, /onNavigate=\{closeNav\}/);
});

test("mobile tables expose field labels and prevent viewport overflow", () => {
  assert.match(sharedSource, /<td key=\{field\} data-label=\{fieldLabel\(field\)\}>/);
  assert.match(cssSource, /td::before\s*\{[\s\S]*content:\s*attr\(data-label\);/);
  assert.match(cssSource, /html,[\s\S]*body[\s\S]*overflow-x:\s*hidden;/);
  assert.match(cssSource, /\.tableWrap\s*\{[\s\S]*overflow:\s*auto;/);
});

test("LLM configuration sections, release dialog, and form inputs keep accessible relationships", () => {
  assert.match(llmSource, /aria-labelledby="available-llms-title"/);
  assert.match(llmSource, /aria-labelledby="node-bindings-title"/);
  assert.match(llmSource, /role="group" aria-label=\{editing \? "编辑 LLM 表单" : "添加 LLM 表单"\}/);
  assert.match(llmSource, /type="password" autoComplete="new-password"/);
  assert.match(releasesSource, /role="dialog" aria-modal="true" aria-labelledby="release-title"/);
  assert.match(releasesSource, /if \(event\.key === "Escape"\)[\s\S]*setSelected\(null\)/);
  assert.match(releasesSource, /restoreFocus\.current\?\.focus\(\)/);
  for (const label of ["评测快照 ID", "发布原因", "幂等键"]) {
    assert.match(releasesSource, new RegExp(`<label>${label}`));
  }
});

test("every custom LLM table cell keeps its field name when mobile headers are hidden", () => {
  const cells = llmSource.match(/<td\b/g) || [];
  const mobileLabels = llmSource.match(/<td\b[^>]*\bdata-label=/g) || [];

  assert.ok(cells.length > 0);
  assert.equal(mobileLabels.length, cells.length);
  for (const label of [
    "名称",
    "厂商 / 模型",
    "Base URL",
    "API Key",
    "状态",
    "操作"
  ]) {
    assert.match(llmSource, new RegExp(`data-label="${label.replace("/", "\\/")}"`));
  }
  for (const label of ["发布记录：", "配置版本：", "提交：", "发布：", "评测：", "回滚发布：", "回滚版本："]) {
    assert.match(releasesSource, new RegExp(label));
  }
});
