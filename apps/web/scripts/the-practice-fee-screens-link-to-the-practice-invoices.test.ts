// PRE-A-018 — the firm-level fee screens (/practice/billing, /practice/ar) generate
// and age the practice's own invoices, and an invoice is confirmed, numbered,
// issued and paid in the sales workspace of the practice's internal client. The
// only way in used to be the "Practice books" button on /accounting, so a Partner
// who had just generated a draft had no way from that screen to the draft.
//
// The rule, not a spelling of it:
//   * a link into the practice's workspace is BUILT BY ONE FUNCTION
//     (lib/invoices/workspaceNav.practiceSalesHref) from an id the SERVER named;
//     no screen writes a `/clients/<id>` path or an id of its own;
//   * the draft link carries the invoice the generate call returned;
//   * what a lookup that failed says is not what "not provisioned" says;
//   * every tab the helper can emit is a tab the Sales screen holds, and the
//     params it writes are the ones that screen reads.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-practice-fee-screens-link-to-the-practice-invoices.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripComments } from "./stripComments.ts";
import { practiceSalesHref, PRACTICE_SALES_TAB_IDS } from "../lib/invoices/workspaceNav.ts";

const BILLING = "app/practice/billing/page.tsx";
const AR = "app/practice/ar/page.tsx";
const SALES = "app/clients/[id]/sales/page.tsx";
const FEE_SCREENS = [BILLING, AR];

const code = (path: string) => stripComments(readFileSync(path, "utf8"));

/** Text a reader sees in a JSX fragment: tags and braces dropped, whitespace folded. */
function readable(jsx: string): string {
  return jsx
    .replace(/\{" "\}/g, " ")
    .replace(/<[^>]*>/g, " ")
    .replace(/[{}]/g, " ")
    .replace(/&apos;/g, "'").replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

/** Every `href={expr}` / `href="literal"` on a Link in a source. */
function linkHrefs(src: string): { dynamic: string[]; literal: string[] } {
  const dynamic: string[] = [];
  const literal: string[] = [];
  for (const m of src.matchAll(/<Link\b[^>]*?\bhref=(?:\{([^}]*)\}|"([^"]*)")/g)) {
    if (m[1] !== undefined) dynamic.push(m[1].trim()); else literal.push(m[2]);
  }
  return { dynamic, literal };
}

for (const path of FEE_SCREENS) {
  test(`${path} links to the practice's invoices only through practiceSalesHref`, () => {
    const src = code(path);
    assert.match(
      src,
      /import\s*\{[^}]*\bpracticeSalesHref\b[^}]*\}\s*from\s*"@\/lib\/invoices\/workspaceNav"/,
      `${path} no longer imports practiceSalesHref`,
    );
    const { dynamic, literal } = linkHrefs(src);
    assert.ok(dynamic.length > 0, `${path} renders no Link whose href is computed`);
    for (const expr of dynamic) {
      // The expression is a name, and that name is a practiceSalesHref result.
      assert.match(expr, /^[A-Za-z_]\w*$/, `${path}: href={${expr}} is not a plain name`);
      assert.match(
        src,
        new RegExp(`\\b(?:const|let)\\s+${expr}\\b[^;]*?\\bpracticeSalesHref\\(`),
        `${path}: href={${expr}} is not built by practiceSalesHref`,
      );
    }
    // The only literal destination is the practice's own setup screen.
    for (const href of literal) {
      assert.equal(href, "/practice", `${path}: a Link to the literal path ${href}`);
    }
    // No screen writes a client path itself, in a template, a literal or a concatenation.
    assert.doesNotMatch(src, /\/clients\//, `${path} writes a /clients/ path instead of asking practiceSalesHref`);
    assert.doesNotMatch(src, /\bsalesListHref\b|\bwithInvoiceParam\b/, `${path} builds a sales path by hand`);
  });

  test(`${path} feeds practiceSalesHref an id the server named, never one it holds`, () => {
    const src = code(path);
    // The id comes from the practice lookup (or the billing options, which names the same client).
    assert.match(src, /api\.practice\.get\(|api\.billing\.serviceOptions\(/, `${path} reads no server answer for the practice`);
    for (const call of src.matchAll(/practiceSalesHref\(([^)]*)\)/g)) {
      const firstArg = call[1].split(",")[0].trim();
      assert.match(
        firstArg,
        /^(internalClientId|books\.clientId)$/,
        `${path}: practiceSalesHref is given ${firstArg}, which is not a server-named id`,
      );
    }
    // No literal id or UUID anywhere on the screen.
    assert.doesNotMatch(src, /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i, `${path} holds a UUID`);
  });
}

test("the generated draft links to the invoice the generate call returned", () => {
  const src = code(BILLING);
  // The id is read off the response of api.billing.generate, not off a list or a guess.
  const gen = src.slice(src.indexOf("api.billing.generate("));
  assert.ok(gen.length > 0, "billing page no longer generates a draft");
  assert.match(gen, /result\??\.invoice\??\.id/, "the draft link no longer uses the generate response's invoice id");
  // That id reaches the banner's link through practiceSalesHref's invoiceId, for a
  // draft this press made AND for the one that was already there.
  assert.match(src, /practiceSalesHref\(internalClientId,\s*\{\s*invoiceId:\s*msgInvoice\?\.id\s*\}\)/);
  assert.match(src, /created:\s*result\?\.created\s*===\s*true/);
  assert.match(src, /msgInvoice\.created\s*\?\s*"Open the draft"\s*:\s*"Open the invoice"/,
    "an invoice that was already generated must not be called a draft: it may have been issued since");
  // The banner link is withheld when there is no practice client to open it in.
  assert.match(src, /draftHref\s*&&\s*msgInvoice/);
});

test("the billing screen says the placeholder number must be replaced before Issue", () => {
  // billing_service numbers every generated draft with draft_placeholder_invoice_no(), and
  // Issue accepts it (Rule 46(b) is a length and charset test), so the screen says so.
  assert.match(readable(code(BILLING)), /placeholder number in Edit before you issue it/);
});

test("the billing screen offers the practice's invoices only once the practice is known", () => {
  const src = code(BILLING);
  // Header link and footer link are both gated on the computed href, so an
  // unprovisioned practice shows the words and no link (the form already tells
  // the CA to provision it).
  assert.match(src, /practiceInvoicesHref\s*&&\s*\(/);
  assert.match(src, /practiceInvoicesHref\s*\?\s*<Link/);
  assert.match(src, /const\s+practiceInvoicesHref\s*=\s*practiceSalesHref\(internalClientId\)\s*;/);
});

test("the AR screen keeps 'known', 'not provisioned' and 'could not look up' three different answers", () => {
  const src = code(AR);
  assert.match(src, /readPracticeBooks\(/, "the AR screen no longer reads the practice through readPracticeBooks");
  // The lookup is its own request, tolerated on its own: a failure of it must not blank the ageing.
  assert.match(src, /api\.practice\.get\(\)\s*\.catch\(/);
  // The ageing request is not the same try as the lookup's failure handling.
  assert.ok(src.indexOf("api.practice.get()") < src.indexOf("api.billing.arAging()"),
    "the lookup is meant to start alongside the ageing, not after it");

  const known = src.indexOf("practiceInvoicesHref && practiceReceiptsHref ?");
  const notProvisioned = src.indexOf('books.state === "not_provisioned" ?');
  const unknownBranch = src.indexOf(") : (", notProvisioned);
  assert.ok(known > 0 && notProvisioned > known && unknownBranch > notProvisioned,
    "the three-way branch is not where this guard expects");
  const end = src.indexOf(")}", unknownBranch);
  const branches = {
    known: src.slice(known, notProvisioned),
    notProvisioned: src.slice(notProvisioned, unknownBranch),
    unknown: src.slice(unknownBranch, end),
  };
  const said = Object.fromEntries(Object.entries(branches).map(([k, v]) => [k, readable(v)]));
  assert.equal(new Set(Object.values(said)).size, 3, `the three branches say the same thing: ${JSON.stringify(said)}`);

  // 'Could not find out' must not claim the practice is not set up: that sends a
  // Partner to provision a practice they already have. And it carries no link,
  // because it has no id to link to.
  assert.doesNotMatch(said.unknown, /not (been )?set up|not provisioned|no practice/i);
  assert.match(said.unknown, /could not look up/i);
  assert.doesNotMatch(branches.unknown, /<Link\b/);
  // 'Not provisioned' says to set the practice up, and points at the screen that does.
  assert.match(said.notProvisioned, /not been set up/i);
  assert.match(branches.notProvisioned, /href="\/practice"/);
  // 'Known' offers the Sales invoices and the Receipts tab, which is where a receipt with TDS is recorded.
  assert.match(src, /practiceSalesHref\(books\.clientId,\s*\{\s*tab:\s*"receipts"\s*\}\)/);
  assert.match(said.known, /Sales invoices/);
  assert.match(said.known, /record a receipt/i);
});

test("the AR screen does not claim the practice is unprovisioned before the server has said so", () => {
  const src = code(AR);
  // The state starts as 'unknown' and the page is held in its loading state
  // until the lookup has settled, so 'could not look up' is never shown for a
  // lookup still in flight.
  assert.match(src, /useState<PracticeBooks>\(\{\s*state:\s*"unknown"\s*\}\)/);
  const finallyBlock = src.slice(src.indexOf("} finally {"), src.indexOf("}, []);"));
  assert.match(finallyBlock, /await lookup/);
  assert.ok(finallyBlock.indexOf("setBooks(") < finallyBlock.indexOf("setLoading(false)"),
    "the page stops loading before the practice lookup has settled");
});

test("every tab a practice screen links to is a tab the Sales screen holds", () => {
  const sales = code(SALES);
  const tabsBlock = sales.slice(sales.indexOf("const TABS"), sales.indexOf("];", sales.indexOf("const TABS")));
  const salesTabs = [...tabsBlock.matchAll(/\bid:\s*"([^"]+)"/g)].map((m) => m[1]);
  assert.ok(salesTabs.length >= 5, "could not read the Sales screen's TABS");
  assert.ok(PRACTICE_SALES_TAB_IDS.length >= 1);
  for (const id of PRACTICE_SALES_TAB_IDS) {
    assert.ok(salesTabs.includes(id), `practiceSalesHref can emit ?tab=${id}, which the Sales screen does not hold (${salesTabs.join(", ")})`);
  }
  // And the tabs the fee screens actually ask for are ones the helper can emit.
  for (const path of FEE_SCREENS) {
    for (const m of code(path).matchAll(/practiceSalesHref\([^)]*\btab:\s*"([^"]+)"/g)) {
      assert.ok(
        (PRACTICE_SALES_TAB_IDS as readonly string[]).includes(m[1]),
        `${path} asks for tab ${m[1]}, which practiceSalesHref does not emit`,
      );
    }
  }
});

test("the params practiceSalesHref writes are the params the Sales screen reads", () => {
  const sales = code(SALES);
  const tab = new URL(practiceSalesHref("c1", { tab: "receipts" }) as string, "http://x");
  const doc = new URL(practiceSalesHref("c1", { invoiceId: "inv-9" }) as string, "http://x");
  assert.equal(tab.pathname, "/clients/c1/sales");
  assert.equal(tab.searchParams.get("tab"), "receipts");
  assert.equal(doc.searchParams.get("invoice"), "inv-9");
  // ?tab= is read (and validated against TABS) by the screen's deep-link effect, and
  // ?invoice= opens the View drawer on the Invoices tab by id.
  assert.match(sales, /tabDeepLinkParams\.get\("tab"\)/);
  assert.match(sales, /TABS\.some\(\(x\)\s*=>\s*x\.id\s*===\s*t\)/);
  assert.match(sales, /p\.get\("invoice"\)\)\s*setDetailId\(p\.get\("invoice"\)\)/);
});

test("the Sales screen's default tab is the one a bare invoice link needs", () => {
  // ?invoice=<id> without ?tab= works only because the Invoices tab is the one the
  // screen opens on, and the drawer is read by that tab.
  assert.match(code(SALES), /useState<SalesTab>\("invoices"\)/);
});
