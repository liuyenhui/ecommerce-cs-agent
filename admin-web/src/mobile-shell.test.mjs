import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

const mainSource = readFileSync(new URL("./main.tsx", import.meta.url), "utf8");
const cssSource = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

test("unauthenticated admin pages render the login task without the backend rail", () => {
  assert.match(mainSource, /function CustomerAdminShell\(/);
  assert.match(mainSource, /function SystemSite\(/);
  assert.match(mainSource, /const isAuthenticated = Boolean\(customerSession\)/);
  assert.match(mainSource, /const isAuthenticated = Boolean\(systemSession\)/);
  assert.match(mainSource, /className=\{`appShell \$\{isAuthenticated \? "isAuthed" : "isGuest"\}/);
  assert.match(mainSource, /\{isAuthenticated \? \(\s*<aside className="rail"/);
  assert.match(cssSource, /\.appShell\.isGuest\s*\{[\s\S]*grid-template-columns:\s*1fr;/);
});

test("authenticated mobile navigation is a collapsible drawer with usable tap targets", () => {
  assert.match(mainSource, /className="mobileNavButton"/);
  assert.match(mainSource, /onToggleNav=\{\(\) => setMobileNavOpen\(\(open\) => !open\)\}/);
  assert.match(mainSource, /onNavigate\?: \(\) => void/);
  assert.match(mainSource, /props\.onNavigate\?\.\(\)/);
  assert.match(cssSource, /\.appShell\.navOpen \.rail\s*\{[\s\S]*transform:\s*translateX\(0\);/);
  assert.match(cssSource, /@media \(max-width: 900px\)[\s\S]*\.rail\s*\{[\s\S]*position:\s*fixed;[\s\S]*transform:\s*translateX\(-100%\);/);
  assert.match(cssSource, /@media \(max-width: 900px\)[\s\S]*button\s*\{[\s\S]*min-height:\s*44px;/);
});
