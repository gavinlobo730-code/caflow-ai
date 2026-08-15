// Every underscore-prefixed file under app/ must be imported by something.
// Run with: node --experimental-strip-types --test scripts/private-components.test.ts
//
// WHY THIS EXISTS
//     `app/**/_page.tsx` looks dead. It is named like `page.tsx`, sits beside a
//     `page.tsx`, and Next.js will not route to it — so reading the tree, the
//     obvious conclusion is that fifteen files ship nothing and should be
//     deleted. I reached exactly that conclusion and was wrong about all of
//     them. Deleting them would have removed six invoice/note editors and the
//     entire Year-End workspace.
//
//     The underscore is load-bearing, in two different ways:
//
//     1. THE STATIC-EXPORT SPLIT. `output: "export"` requires
//        generateStaticParams() on every dynamic segment, and that cannot live
//        in a "use client" file. So page.tsx is a nine-line server shim that
//        exports generateStaticParams and renders the client component next to
//        it. The client component has to be named something Next.js will NOT
//        treat as a route — hence `_page.tsx`.
//
//     2. THE TAB CONSOLIDATION. The eight Year-End stages were eight routes;
//        each dynamic route costs two of Cloudflare Pages' hard limit of 100
//        _redirects rules. They are now eight tab panels imported by
//        _workspace.tsx, on one route, and the underscore is what stops them
//        being routes again. See the comment at the top of _workspace.tsx.
//
//     A genuinely orphaned underscore file would be invisible: no route, no
//     importer, no build error, nothing to notice. This test is the only thing
//     that would say so — and, read the other way, it is what fails loudly if
//     someone tries to delete one that is still wired up.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { sourceFilesUnder } from "./await-waterfalls.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

/** Underscore-prefixed source files under app/ — components by convention,
 *  never routes. */
function privateComponents(): string[] {
  return sourceFilesUnder(path.join(WEB, "app"), fs, path)
    .filter((f) => path.basename(f).startsWith("_"));
}

/** Resolve an import specifier the way tsconfig does: "@/x" from the web root,
 *  "./x" and "../x" relative to the importer, extensions implicit. */
function resolveSpecifier(fromFile: string, spec: string): string | null {
  let base: string;
  if (spec.startsWith("@/")) base = path.join(WEB, spec.slice(2));
  else if (spec.startsWith(".")) base = path.resolve(path.dirname(fromFile), spec);
  else return null;                       // a package, not a file in this repo

  for (const candidate of [
    base, `${base}.tsx`, `${base}.ts`,
    path.join(base, "index.tsx"), path.join(base, "index.ts"),
  ]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  return null;
}

/** Every in-repo file that is imported by any source file. */
function importedFiles(): Set<string> {
  const out = new Set<string>();
  for (const dir of ["app", "components", "lib", "scripts"]) {
    for (const file of sourceFilesUnder(path.join(WEB, dir), fs, path)) {
      const sf = ts.createSourceFile(
        file, fs.readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      const visit = (n: ts.Node): void => {
        let spec: string | null = null;
        if (ts.isImportDeclaration(n) && ts.isStringLiteral(n.moduleSpecifier)) {
          spec = n.moduleSpecifier.text;
        } else if (ts.isExportDeclaration(n) && n.moduleSpecifier &&
                   ts.isStringLiteral(n.moduleSpecifier)) {
          spec = n.moduleSpecifier.text;
        } else if (ts.isCallExpression(n) &&
                   n.expression.kind === ts.SyntaxKind.ImportKeyword &&
                   n.arguments.length > 0 && ts.isStringLiteral(n.arguments[0])) {
          spec = n.arguments[0].text;      // dynamic import()
        }
        if (spec) {
          const resolved = resolveSpecifier(file, spec);
          if (resolved) out.add(resolved);
        }
        ts.forEachChild(n, visit);
      };
      ts.forEachChild(sf, visit);
    }
  }
  return out;
}

test("every underscore-prefixed file under app/ is imported by something", () => {
  const imported = importedFiles();
  const orphans = privateComponents()
    .filter((f) => !imported.has(f))
    .map((f) => path.relative(WEB, f))
    .sort();

  assert.deepEqual(
    orphans, [],
    "Underscore-prefixed file(s) under app/ that nothing imports. Next.js does " +
    "not route to them either, so they ship nothing and no build error would " +
    "ever mention them — either wire them up or delete them:\n" +
    orphans.map((f) => `  ${f}`).join("\n"),
  );
});

test("the six static-export shims still render their client component", () => {
  // The specific pairing that makes these files live: a nine-line page.tsx
  // holding generateStaticParams (which cannot be in a "use client" file)
  // beside the real screen. If a shim ever stops importing its sibling, the
  // route renders nothing and the test above would still pass as long as
  // something else imported it.
  const shims = [
    "app/clients/[id]/sales/invoices/[invoiceId]/edit",
    "app/clients/[id]/sales/credit-notes/[cnId]/edit",
    "app/clients/[id]/sales/debit-notes/[sdnId]/edit",
    "app/clients/[id]/purchases/bills/[billId]/edit",
    "app/clients/[id]/purchases/credit-notes/[pcnId]/edit",
    "app/clients/[id]/purchases/debit-notes/[dnId]/edit",
  ];
  for (const dir of shims) {
    const shim = path.join(WEB, dir, "page.tsx");
    const client = path.join(WEB, dir, "_page.tsx");
    assert.ok(fs.existsSync(shim), `${dir}/page.tsx is missing — the route is gone`);
    assert.ok(fs.existsSync(client), `${dir}/_page.tsx is missing — the screen is gone`);
    const src = fs.readFileSync(shim, "utf8");
    assert.match(src, /from\s+"\.\/_page"/, `${dir}/page.tsx no longer renders its client component`);
    assert.match(src, /generateStaticParams/,
      `${dir}/page.tsx lost generateStaticParams — the static export will fail on this dynamic segment`);
  }
});

test("all eight Year-End stages are still wired into the one workspace route", () => {
  // The consolidation is only correct while every stage is reachable. A stage
  // dropped from this list becomes an underscore file with no importer, which
  // the first test catches — but this says which stage and why it matters.
  const workspace = fs.readFileSync(
    path.join(WEB, "app/clients/[id]/year-end/[engagementId]/_workspace.tsx"), "utf8");
  const stages = ["dashboard", "checklist", "adjustments", "schedules",
                  "financial-statements", "notes", "review", "exports"];
  for (const stage of stages) {
    assert.match(workspace, new RegExp(`from "\\./${stage}/_page"`),
      `the ${stage} stage is no longer imported — that stage is unreachable`);
  }
  // And none of them may become a route again: that is what the underscore buys,
  // and the redirect budget it protects is a hard Cloudflare limit, not a
  // preference.
  for (const stage of stages) {
    const asRoute = path.join(WEB, "app/clients/[id]/year-end/[engagementId]", stage, "page.tsx");
    assert.ok(!fs.existsSync(asRoute),
      `${stage}/page.tsx exists again — that re-adds a dynamic route and costs ` +
      `two of Cloudflare's 100 _redirects rules`);
  }
});

test("the guard is reading real files, not an empty tree", () => {
  const found = privateComponents();
  assert.ok(found.length >= 14, `only ${found.length} underscore files found under app/`);
});
