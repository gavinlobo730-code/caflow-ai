// POST-A-543. The one table of which permission opens which area and screen, tested as plain code.
//   node --experimental-strip-types --test lib/access/screenAccess.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { AREA_RULES, SCREEN_RULES, areaOffered, everyPair, mayOpen, pairToAsk, ruleHeld, screenRule, type Asker } from "./screenAccess.ts";

const API = join(import.meta.dirname, "..", "..", "..", "api");
const holding = (pairs: string[], isPartner = false): Asker => ({ can: (r, a) => pairs.includes(`${r}:${a}`), isPartner });
const everything = (isPartner = false): Asker => ({ can: () => true, isPartner });
const nothing = (isPartner = false): Asker => ({ can: () => false, isPartner });

test("a rule: all must hold, one of any must hold, and Partner-only asks the role and no permission", () => {
  assert.equal(ruleHeld({}, nothing()), true, "an empty rule is always held");
  assert.equal(ruleHeld({ all: [["a", "read"], ["b", "read"]] }, holding(["a:read"])), false);
  assert.equal(ruleHeld({ all: [["a", "read"], ["b", "read"]] }, holding(["a:read", "b:read"])), true);
  assert.equal(ruleHeld({ any: [["a", "read"], ["b", "read"]] }, holding(["b:read"])), true);
  assert.equal(ruleHeld({ any: [["a", "read"], ["b", "read"]] }, nothing()), false);
  assert.equal(ruleHeld({ partnerOnly: true }, everything(false)), false, "a tick opened a Partner-only rule");
  assert.equal(ruleHeld({ partnerOnly: true }, nothing(true)), true);
});

test("the pair a notice names: the first of `all` the person lacks, else the first of `any`; none for Partner-only", () => {
  assert.deepEqual(pairToAsk({ all: [["a", "read"], ["b", "read"]] }, holding(["a:read"])), ["b", "read"]);
  assert.deepEqual(pairToAsk({ any: [["a", "read"], ["b", "read"]] }, nothing()), ["a", "read"]);
  assert.equal(pairToAsk({ any: [["a", "read"]] }, holding(["a:read"])), null);
  assert.equal(pairToAsk({ partnerOnly: true }, nothing()), null);
});

test("Home is always offered, and an address no area owns is not this table's to refuse", () => {
  assert.equal(areaOffered("home", nothing()), true);
  for (const address of ["/", "/notifications", "/notifications/whatsapp", "/search", "/settings", "/settings/security"]) {
    assert.equal(mayOpen(address, nothing()).allowed, true, address);
  }
});

test("an address is opened by its AREA's rule and then its own: a screen is never open inside an area the menu does not show", () => {
  // The area refuses first, and the notice then names the area.
  const noBooks = mayOpen("/accounting/banking", holding(["client:read"]));
  assert.deepEqual([noBooks.allowed, noBooks.byArea, noBooks.area, noBooks.ask], [false, true, "accounting", ["accounting", "read"]]);
  // The area is theirs and the screen asks something more.
  const noBilling = mayOpen("/accounting/retainer", holding(["accounting:read"]));
  assert.deepEqual([noBilling.allowed, noBilling.byArea, noBilling.ask], [false, false, ["billing", "read"]]);
  assert.equal(mayOpen("/accounting/retainer", holding(["accounting:read", "billing:read"])).allowed, true);
  // A screen with no rule of its own is its area's.
  assert.equal(mayOpen("/accounting/budget", holding(["accounting:read"])).allowed, true);
  assert.equal(mayOpen("/relationships/explorer", holding(["client:read"])).allowed, true);
});

test("the longest prefix is the screen's rule, with or without a trailing slash, a query or a fragment", () => {
  assert.deepEqual(screenRule("/income-tax/book-to-tax"), { all: [["income_tax", "compute"]] });
  assert.deepEqual(screenRule("/income-tax/book-to-tax/"), { all: [["income_tax", "compute"]] });
  assert.deepEqual(screenRule("/income-tax/season?fy=2026-27"), { all: [["income_tax", "read"]] });
  assert.deepEqual(screenRule("/team/assignments#x"), { all: [["assignment", "read"]] });
  assert.equal(screenRule("/teams"), null, "a prefix matched an address that only starts with the same letters");
  assert.equal(screenRule("/"), null);
});

test("each tax desk is opened by its own tick, and the three computation screens by the compute permission", () => {
  const desks: Array<[string, string]> = [["/gst", "gst:read"], ["/gst/gstr1", "gst:read"], ["/income-tax", "income_tax:read"], ["/tds", "tds:read"], ["/tds/returns", "tds:read"], ["/mca", "mca:read"]];
  for (const [address, pair] of desks) {
    assert.equal(mayOpen(address, holding(["compliance:read", pair])).allowed, true, address);
    assert.equal(mayOpen(address, holding(["compliance:read"])).allowed, false, `${address} opened without ${pair}`);
  }
  for (const address of ["/income-tax/book-to-tax", "/income-tax/section-32", "/income-tax/deductions"]) {
    assert.equal(mayOpen(address, holding(["income_tax:read"])).allowed, false, `${address}: the server refuses its read to somebody who cannot compute`);
    assert.equal(mayOpen(address, holding(["income_tax:read", "income_tax:compute"])).allowed, true, address);
  }
});

test("inside a client only the area's rule is asked: the client's sections have their own", () => {
  assert.equal(mayOpen("/clients/abc/payroll", holding(["client:read"])).allowed, true);
  assert.equal(mayOpen("/clients/abc/documents", holding(["client:read"])).allowed, true);
  assert.equal(mayOpen("/clients/abc/accounting", nothing()).allowed, false);
  // The two firm screens under /clients are screens of the firm, with their own rule.
  assert.equal(mayOpen("/clients/documents", holding(["client:read"])).allowed, false);
  assert.equal(mayOpen("/clients/documents", holding(["client:read", "document:read"])).allowed, true);
});

test("every pair the table names is a pair of the server's table", () => {
  const src = readFileSync(join(API, "core", "permissions.py"), "utf8");
  const pairs = everyPair();
  assert.ok(pairs.length >= 60, `only ${pairs.length} pairs read`);
  for (const [resource, action] of pairs) {
    const at = src.indexOf(`"${resource}": {`);
    assert.ok(at >= 0, `${resource} is not a resource of core/permissions.py`);
    assert.match(src.slice(at, src.indexOf("},", at)), new RegExp(`"${action}":`), `${resource}:${action} is not a pair of core/permissions.py`);
  }
});

test("the table has no prefix twice, and every screen rule sits in an area that has a rule", () => {
  const prefixes = SCREEN_RULES.map(([p]) => p);
  assert.equal(new Set(prefixes).size, prefixes.length, "a prefix is listed twice: which rule wins would be an accident of order");
  for (const [prefix] of SCREEN_RULES) {
    const area = mayOpen(prefix, everything(true)).area;
    // No area owns the Settings addresses (POST-A-545): a Settings page is opened by its own rule alone.
    if (prefix.startsWith("/settings/")) { assert.equal(area, null, `${prefix} is a Settings page and an area claims it`); continue; }
    assert.ok(area && area in AREA_RULES, `${prefix} is in no area of the firm menu`);
  }
});

test("a Settings page is opened by the pair its own read asks, and the Settings home and a person's own security page by nothing", () => {
  const holds = (...pairs: string[]) => ({ can: (r: string, a: string) => pairs.includes(`${r}:${a}`), isPartner: false });
  const cases: Array<[string, string]> = [
    ["/settings/ai", "firm:admin"], ["/settings/audit-log", "audit:read"], ["/settings/branding", "branding:read"],
    ["/settings/email-templates", "branding:read"], ["/settings/invoice-settings", "branding:read"],
    ["/settings/invoice-templates", "branding:read"], ["/settings/firm-hsn-library", "accounting:read"],
    ["/settings/journal-approval", "accounting:read"], ["/settings/multi-currency", "settings:read"],
    ["/settings/statutory-values", "payroll:read"], ["/settings/treaty-rates", "tds:read"]];
  for (const [href, pair] of cases) {
    assert.equal(mayOpen(href, holds(pair)).allowed, true, `${href} is refused to somebody who holds ${pair}`);
    const refused = mayOpen(`${href}/`, holds());
    assert.equal(refused.allowed, false, `${href} opens for somebody who holds nothing`);
    assert.deepEqual(refused.ask?.join(":"), pair, `${href} asks for something other than the pair its read asks`);
    assert.equal(refused.byArea, false);
    // The WRITE pair alone does not open a page whose read asks another: the page would be drawn around a refused read.
  }
  assert.equal(SCREEN_RULES.filter(([p]) => p.startsWith("/settings/")).length, cases.length, "a Settings rule this test has not read");
  for (const href of ["/settings", "/settings/security", "/settings/scheduled-reports", "/settings/dsc-tracker"]) {
    assert.equal(mayOpen(href, holds()).allowed, true, `${href} is every member's and was refused`);
  }
});
