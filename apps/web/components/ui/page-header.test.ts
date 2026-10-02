/**
 * PageHeader, rendered (frontend_ux-13). Run with:
 *   node --experimental-strip-types --test components/ui/page-header.test.ts
 *
 * `pnpm test` is `node --experimental-strip-types --test`, which strips types
 * but does not parse JSX, so a `.tsx` component cannot simply be imported. This
 * transpiles the REAL page-header.tsx with the TypeScript compiler already in
 * node_modules and renders it with react-dom/server, with `next/link` and
 * `lucide-react` replaced by two-line stand-ins (a link is an anchor, an icon is
 * a named svg) — everything else, including `cn`, is the product's own code. It
 * is the closest this suite gets to opening the screen, and it says so: no
 * browser, no layout, no pixels.
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";

const WEB = path.resolve(import.meta.dirname, "../..");
let dir = "";
let PageHeader: (props: Record<string, unknown>) => React.ReactElement;

before(async () => {
  dir = fs.mkdtempSync(path.join(WEB, ".page-header-test-"));
  const source = fs.readFileSync(path.join(WEB, "components/ui/page-header.tsx"), "utf8");
  let js = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  js = js
    .replace('"next/link"', '"./link.mjs"')
    .replace('"lucide-react"', '"./icons.mjs"')
    .replace('"@/lib/utils"', JSON.stringify(pathToFileURL(path.join(WEB, "lib/utils.ts")).href));
  fs.writeFileSync(path.join(dir, "link.mjs"),
    'import React from "react";\n' +
    'export default function Link({ href, children, ...rest }) {\n' +
    '  return React.createElement("a", { href, ...rest }, children);\n}\n');
  fs.writeFileSync(path.join(dir, "icons.mjs"),
    'import React from "react";\n' +
    'const icon = (name) => (props) => React.createElement("svg", { "data-icon": name, "aria-hidden": props["aria-hidden"] });\n' +
    'export const ChevronLeft = icon("ChevronLeft");\n' +
    'export const ChevronRight = icon("ChevronRight");\n');
  fs.writeFileSync(path.join(dir, "page-header.mjs"), js);
  const mod = await import(pathToFileURL(path.join(dir, "page-header.mjs")).href);
  PageHeader = mod.PageHeader;
});

after(() => {
  if (dir) fs.rmSync(dir, { recursive: true, force: true });
});

function html(props: Record<string, unknown>): string {
  return renderToStaticMarkup(React.createElement(PageHeader, props));
}

test("a screen's name is one h1 in one style, whatever else is passed", () => {
  const out = html({ title: "Fee Billing", subtitle: "Manage fee engagements", actions: "x" });
  assert.equal((out.match(/<h1/g) ?? []).length, 1);
  assert.match(out, /<h1 class="text-xl font-semibold text-ps-ink">Fee Billing<\/h1>/);
});

test("a string subtitle is a paragraph and a rich one is not nested in a paragraph", () => {
  const plain = html({ title: "T", subtitle: "one line" });
  assert.match(plain, /<p class="[^"]*text-sm text-ps-label">one line<\/p>/);
  const rich = html({
    title: "T",
    subtitle: React.createElement("span", null, "a ", React.createElement("div", null, "block")),
  });
  assert.doesNotMatch(rich, /<p\b/, "a block inside a <p> is invalid nesting");
  assert.match(rich, /<div class="[^"]*text-sm text-ps-label"><span>a <div>block<\/div><\/span><\/div>/);
});

test("an absent subtitle renders nothing, not an empty line", () => {
  for (const sub of [undefined, null, false]) {
    assert.doesNotMatch(html({ title: "T", subtitle: sub }), /text-ps-label/);
  }
});

test("the back link is LABELLED, goes where it was told, and sits above the title", () => {
  const out = html({ title: "Firm Branding", back: { href: "/settings", label: "Settings" } });
  assert.match(out, /<a href="\/settings"[^>]*>.*Settings<\/a>/);
  assert.ok(out.indexOf("Settings</a>") < out.indexOf("<h1"), "the back link must precede the title");
  // an icon alone has no accessible name, so the link may never be icon-only
  assert.match(out, /<svg data-icon="ChevronLeft" aria-hidden="true"><\/svg> Settings/);
});

test("breadcrumbs link every crumb but the last, which is the current page", () => {
  const out = html({
    title: "WhatsApp Quick-Compose",
    breadcrumbs: [{ label: "Notifications", href: "/notifications" }, { label: "WhatsApp Quick-Compose" }],
  });
  assert.match(out, /<nav aria-label="Breadcrumb"/);
  assert.match(out, /<a href="\/notifications"[^>]*>Notifications<\/a>/);
  assert.match(out, /<span aria-current="page">WhatsApp Quick-Compose<\/span>/);
  assert.equal((out.match(/<a /g) ?? []).length, 1, "the current page is not a link");
});

test("breadcrumbs win over a back link, and an empty list falls back to it", () => {
  const both = html({
    title: "T", back: { href: "/b", label: "Back" },
    breadcrumbs: [{ label: "Crumb", href: "/c" }, { label: "Here" }],
  });
  assert.match(both, /Crumb/);
  assert.doesNotMatch(both, /href="\/b"/);
  const empty = html({ title: "T", back: { href: "/b", label: "Back" }, breadcrumbs: [] });
  assert.match(empty, /href="\/b"/);
});

test("the actions sit beside the title block, after it, and wrap rather than squeeze it", () => {
  const out = html({ title: "Clients", actions: React.createElement("button", null, "Add Client") });
  assert.ok(out.indexOf("<h1") < out.indexOf("<button"), "actions follow the title in the DOM");
  assert.match(out, /^<div class="flex flex-wrap items-start justify-between/);
  assert.match(out, /<div class="flex flex-wrap items-center gap-2"><button>Add Client<\/button><\/div>/);
  assert.doesNotMatch(html({ title: "Clients" }), /gap-2"><\/div>/, "no empty actions slot");
});

test("icon and meta share the title's line; the icon is hidden from assistive tech", () => {
  const out = html({
    title: "Knowledge Base", icon: React.createElement("i", null), meta: React.createElement("em", null, "3 articles"),
  });
  const row = out.slice(out.indexOf("<span aria-hidden"), out.indexOf("</em>") + "</em>".length);
  assert.match(row, /aria-hidden="true"/);
  assert.match(row, /<h1[^>]*>Knowledge Base<\/h1><em>3 articles<\/em>/);
});

test("children render under the title block, and a caller's className reaches the root", () => {
  const out = html({ title: "T", subtitle: "S", className: "mb-6 print:hidden", children: React.createElement("nav", null, "sub") });
  assert.match(out, /^<div class="[^"]*mb-6 print:hidden"/);
  assert.ok(out.indexOf("S</p>") < out.indexOf("<nav>sub"), "children come after the subtitle");
});
