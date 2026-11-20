// POST-A-447. A menu entry gated by POST-A-447 asks the pair its page's first call asks, read off the route or the
// row-level policy in the API source, and the page still makes that call. And the two chart-of-accounts screens that
// a reader may open do not offer them a write the server refuses.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const API = join(WEB, "..", "api");
const read = (...p: string[]) => readFileSync(join(...p), "utf8");

/** The `requires` pair a panel gives the entry for `href`, or null. */
function panelPair(panel: string, href: string): string | null {
  const src = read(WEB, "components", "panels", `${panel}.tsx`);
  const at = src.indexOf(`href: "${href}"`);
  assert.ok(at >= 0, `${panel} no longer lists ${href}`);
  const entry = src.slice(src.lastIndexOf("{", at), src.indexOf("}", at) + 1);
  const m = entry.match(/requires:\s*\["([a-z_]+)",\s*"([a-z_]+)"\]/);
  return m ? `${m[1]}:${m[2]}` : null;
}

/** The pair a GET route asks, read from the router. */
function routePair(router: string, path: string): string {
  const src = read(API, "routers", router);
  const at = src.indexOf(`@router.get("${path}")`);
  assert.ok(at >= 0, `${router} has no GET ${path}`);
  const next = src.indexOf("@router.", at + 1);
  const m = src.slice(at, next < 0 ? undefined : next).match(/rbac\("([a-z_]+)",\s*"([a-z_]+)"\)/);
  assert.ok(m, `GET ${path} in ${router} asks no pair`);
  return `${m[1]}:${m[2]}`;
}

test("Memory & Signals asks what the triggers list asks, and the page opens on it", () => {
  assert.equal(panelPair("AIPanel", "/memory"), routePair("memory_intelligence.py", "/triggers"));
  assert.match(read(WEB, "app", "memory", "page.tsx"), /api\.memory\.listTriggers\(/);
});

test("Risk Intelligence asks what the register asks, and the page opens on it", () => {
  assert.equal(panelPair("AIPanel", "/risks"), routePair("risks.py", "/register"));
  assert.match(read(WEB, "app", "risks", "page.tsx"), /api\.risks\.register\(/);
});

test("the AI panel filters on its pairs and does not list every entry to everyone", () => {
  const src = read(WEB, "components", "panels", "AIPanel.tsx");
  assert.match(src, /AI_ITEMS\.filter\(/);
  assert.doesNotMatch(src, /\{AI_ITEMS\.map\(/);
});

test("Schedule III Mapping asks what the statements route asks, and the page reads it", () => {
  assert.equal(panelPair("AccountingPanel", "/accounting/schedule-iii-mapping"), routePair("accounting.py", "/schedule-iii"));
  assert.match(read(WEB, "app", "accounting", "schedule-iii-mapping", "page.tsx"), /api\.accounting\.scheduleIii\(/);
});

test("the earlier fee receivables are on the Partner's own menu, and billing read is who the fee table's policy lets read it", () => {
  // The entry left the Accounting menu (where it asked billing:read) for My practice on 21-11-2026 (POST-B-193). That panel
  // carries no pair per entry because the whole workspace is the Partner's, and billing read is Partner-only.
  assert.equal(panelPair("PracticePanel", "/accounting/receivables"), null);
  assert.doesNotMatch(read(WEB, "components", "panels", "AccountingPanel.tsx"), /href: "\/accounting\/receivables"/);
  assert.match(read(API, "core", "permissions.py"), /"billing": \{\s*"read":\s*_PARTNER_ONLY/);
  assert.match(read(WEB, "app", "accounting", "receivables", "page.tsx"), /\.from\("fee_invoices"\)/);
  const policy = read(API, "migrations", "495_the_practices_fee_tables_are_read_only_by_someone_with_billing_access.sql");
  assert.match(policy, /fee_invoices/);
  assert.match(policy, /'billing'/);
});

test("Import COA asks accounting write, the tier of the chart's write policy, and the page writes the chart", () => {
  assert.equal(panelPair("AccountingPanel", "/accounting/coa-import"), "accounting:write");
  assert.match(read(WEB, "app", "accounting", "coa-import", "page.tsx"), /\.from\("chart_of_accounts"\)\.insert\(/);
  assert.match(read(API, "migrations", "260_role_aware_write_policies.sql"), /\['chart_of_accounts',\s*'Manager',\s*'Manager'\]/);
  assert.match(read(API, "core", "permissions.py"), /"accounting": \{\s*"read":\s*_AT_LEAST_EXECUTIVE,\s*"write":\s*_AT_LEAST_MANAGER/);
});

test("the chart's two write screens offer the change only to someone who may write the books", () => {
  const mapping = read(WEB, "app", "accounting", "schedule-iii-mapping", "page.tsx");
  assert.match(mapping, /const mayEdit = resolved && can\("accounting", "write"\)/);
  assert.match(mapping, /const picker = \(acc: CoaRow\) => !mayEdit \?/, "the caption picker is drawn to a reader again");
  const groups = read(WEB, "app", "accounting", "account-groups", "page.tsx");
  const guarded = groups.match(/<Can resource="accounting" action="write">/g) ?? [];
  assert.equal(guarded.length, 2, "Add ledger and Edit are each inside a Can for accounting write");
  for (const label of ["Add ledger", ">Edit</button>"]) {
    const at = groups.indexOf(label);
    assert.ok(at > groups.lastIndexOf('<Can resource="accounting" action="write">', at), `${label} is outside its Can`);
  }
  // Both routes the buttons reach ask accounting write.
  const acc = read(API, "routers", "accounting.py");
  for (const decl of ['@router.post("/accounts")', '@router.patch("/accounts/{account_id}")']) {
    const at = acc.indexOf(decl);
    assert.ok(at >= 0, `${decl} is gone`);
    assert.match(acc.slice(at, acc.indexOf("@router.", at + 1)), /rbac\("accounting", "write"\)/);
  }
});
