// A POST that only ASKS is said as a question and sent again after a cold start, and only the POSTs read on the server may say so (POST-A-414).
// Run with:
//   node --experimental-strip-types --test scripts/a-post-that-only-asks-is-on-the-named-list.test.ts
//
// WHY THIS EXISTS
//     `request()` words a failure by the request's METHOD (POST-A-406) and never sends a change a second time (POST-A-412): a POST that got no
//     answer may have gone through. That is right for a change and wrong for a POST that only asks, a preview or a check that writes nothing:
//     a posting preview that got no answer after the server had slept was told "it is not known whether it went through" and was not tried again,
//     although there was nothing to go through. `asked: "read"` on the call says it only asks, and `request()` then treats it as a read.
//
// THE RULE
//     * every call that carries `asked: "read"` is a POST to one of the endpoints named below, and every endpoint named below carries it;
//     * each name is a POST that was read on the server, handler and every function it calls, and writes nothing: no row, no audit entry, no
//       journal, no file, no mail and no model call (a mistaken entry would send a change twice, which is why the list is named and not inferred
//       from a word in the path: `/api/health/scores/{id}/calculate` stores a score and `/api/memory/clients/{id}/profile/compute` stores a profile);
//     * `request()` takes `asked` off before the request is made, and reads it before it decides whether a failure may be sent again.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const WEB = path.join(import.meta.dirname, "..");

/** The POSTs that only ask, each with the server handler that was read (16-11-2026) and what it does instead of writing. */
const ASKS_ONLY: Record<string, string> = {
  "/api/fx-revaluation/preview": "routers/fx_revaluation.py preview_revaluation: plans the AS 11 revaluation from reads; only revalue() writes",
  "/api/inventory/items/{}/writedown-preview": "routers/inventory.py preview_writedown_stock_to_nrv: domain.inventory_service.preview_nrv_writedown, reads the stock ledger",
  "/api/banking/transactions/{}/posting-preview": "routers/banking.py posting_preview: bank_posting_service.preview plans the journal; only post() writes",
  "/api/banking/reconciliations/{}/preview": "routers/banking.py preview_reconciliation: bank_reconciliation_service.preview classifies and ties out; reconcile() writes",
  "/api/payroll/runs/{}/esic/mapped-ips": "routers/payroll.py esic_mapped_ip_check: compares the pasted list with the run's return and stores nothing",
  "/api/payroll/employees/{}/settlement": "routers/payroll.py preview_settlement: composes the settlement; the record door is /settlement/record",
  "/api/billing/preview-run": "routers/billing.py preview_run: billing_service.preview_due lists what would be generated",
};

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
    const rel = path.posix.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(rel));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && !/\.d\.ts$/.test(entry.name)) out.push(rel);
  }
  return out;
}

/** A request path with its interpolations as `{}` and its query string dropped. */
function pathOf(arg: ts.Expression, sf: ts.SourceFile): string | null {
  let text: string;
  if (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)) text = arg.text;
  else if (ts.isTemplateExpression(arg)) text = arg.getText(sf).slice(1, -1);
  else return null;
  return text.replace(/\$\{(?:[^{}]|\{[^{}]*\})*\}/g, "{}").split("?")[0].replace(/\{\}$/, (m) => (text.includes("?") ? "" : m));
}

/** Every call to `request(...)` that carries `asked: "read"`: its path and its method. */
function labelledCalls(rel: string, src: string): { path: string | null; method: string | null; at: string }[] {
  const sf = ts.createSourceFile(rel, src, ts.ScriptTarget.Latest, true, rel.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: { path: string | null; method: string | null; at: string }[] = [];
  const visit = (n: ts.Node) => {
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "request" && n.arguments.length >= 2) {
      const opts = n.arguments[1];
      if (ts.isObjectLiteralExpression(opts)) {
        const prop = (name: string) => opts.properties.find((p) => ts.isPropertyAssignment(p) && p.name.getText(sf) === name) as ts.PropertyAssignment | undefined;
        const asked = prop("asked");
        if (asked && ts.isStringLiteral(asked.initializer) && asked.initializer.text === "read") {
          const method = prop("method");
          out.push({
            path: pathOf(n.arguments[0], sf),
            method: method && ts.isStringLiteral(method.initializer) ? method.initializer.text : null,
            at: `${rel}:${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}`,
          });
        }
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

test("every POST marked as only asking is on the named list, and every name on the list is marked", () => {
  const calls = ["app", "components", "lib"].flatMap(sourceFiles).flatMap((f) => labelledCalls(f, read(f)));
  for (const c of calls) {
    assert.equal(c.method, "POST", `${c.at}: only a POST needs the mark (a GET is already a read)`);
    assert.ok(c.path && c.path in ASKS_ONLY, `${c.at}: ${c.path} is marked as only asking and is not on the named list (read its handler first)`);
  }
  assert.deepEqual([...new Set(calls.map((c) => c.path))].sort(), Object.keys(ASKS_ONLY).sort(), "a named POST lost its mark, or the list names one nothing calls");
});

test("request() takes the mark off before the request is made and reads it before it decides whether to send again", () => {
  const src = read("lib/api/index.ts");
  assert.match(src, /const \{ asked, \.\.\.rest \} = requestOptions \?\? \{\};/, "the mark is passed on to fetch");
  assert.match(src, /const doing = asked === "read" \? "read" : doingOf\(options\?\.method\);/, "the mark does not decide what the request was");
  assert.match(src, /if \(doing === "write"\) throw plainFailure\(e, doing\);\s*await sleep\(5_000\);/, "a change is sent a second time");
});

test("every reason on the list names the handler that was read", () => {
  for (const [p, why] of Object.entries(ASKS_ONLY)) {
    assert.match(why, /^routers\/\w+\.py \w+: /, `${p}: the reason does not name its handler`);
  }
});

test("self-test: a marked POST that is not on the list, and a marked GET, are found", () => {
  const found = labelledCalls("Sample.ts", `
    const a = () => request(\`/api/health/scores/\${id}/calculate\`, { method: "POST", asked: "read" });
    const b = () => request("/api/thing", { asked: "read" });
    const c = () => request(\`/api/billing/preview-run\${asOf ? \`?as_of=\${asOf}\` : ""}\`, { method: "POST", asked: "read" });`);
  assert.deepEqual(found.map((c) => [c.path, c.method]), [["/api/health/scores/{}/calculate", "POST"], ["/api/thing", null], ["/api/billing/preview-run", "POST"]]);
});
