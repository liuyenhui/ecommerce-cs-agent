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

test("desktop collapsed navigation stays accessible and exactly 64 pixels wide", () => {
  assert.match(cssSource, /\.appShell\.railCollapsed\s*\{[\s\S]*grid-template-columns:\s*64px minmax\(0, 1fr\);/);
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

test("LLM tabs, release dialog, and form inputs keep accessible relationships", () => {
  assert.match(llmSource, /role="tablist" aria-label="LLM 治理功能"/);
  assert.match(llmSource, /role="tab" aria-selected=\{tab === key\}/);
  assert.match(llmSource, /aria-controls=\{`llm-panel-\$\{key\}`\}/);
  assert.match(llmSource, /role="tabpanel"[\s\S]*aria-labelledby="llm-tab-config"/);
  assert.match(releasesSource, /role="dialog" aria-modal="true" aria-labelledby="release-title"/);
  assert.match(releasesSource, /if \(event\.key === "Escape"\)[\s\S]*setSelected\(null\)/);
  assert.match(releasesSource, /restoreFocus\.current\?\.focus\(\)/);
  for (const label of ["评测快照 ID", "发布原因", "幂等键"]) {
    assert.match(releasesSource, new RegExp(`<label>${label}`));
  }
});
