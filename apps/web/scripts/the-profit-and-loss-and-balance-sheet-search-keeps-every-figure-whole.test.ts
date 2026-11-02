// The Profit and Loss and the Balance Sheet can be narrowed to the accounts a person is looking for, and every figure stays whole (POST-A-136).
//
// WHAT WAS MISSING
//   The Trial Balance had a search and a type filter (31-10-2026) and the other two statements did not. The remainder was a design
//   question: both statements are presented by Schedule III caption, so a filtered account list would sit under caption subtotals that are
//   for the whole caption. Decided on 2-11-2026: the filter chooses which ACCOUNT ROWS are drawn under each caption and nothing else.
//   A caption that has no matching account keeps its heading and its whole figure, every total is the server's, and a sentence says so
//   whenever a filter is on. (Hiding the captions with no match would make the figures stop adding up on the page.)
//
// WHAT THIS HOLDS
//   * a caption's figure is the sum of ALL its accounts and the rows drawn come from the filter, in both section components;
//   * no total is taken from the rows drawn, and every call site passes the filter to its section;
//   * each statement keeps its filter in its own state, returns to "no filter" when the client changes, and shows the one bar;
//   * the bar names its two controls, shows the type choice only when there is more than one type, says in a sentence what the figures
//     are figures OF while a filter is on (and the sentence prints; the controls do not), and the sentence is the module's;
//   * rendered: the sentence appears with a filter and not without, and the type choice appears only for two or more types.
//
// Run with: node --experimental-strip-types --test scripts/the-profit-and-loss-and-balance-sheet-search-keeps-every-figure-whole.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";
import { loadModule, requireFromWeb } from "./tsxHarness.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const PAGE = read("app/clients/[id]/accounting/page.tsx");
const BAR = read("components/accounting/StatementFilterBar.tsx");
const FILTER = read("lib/accounting/trialBalanceFilter.ts");

/** The source of one top-level function of the page: from its declaration to the next top-level function. */
function fn(name: string): string {
  const at = PAGE.indexOf(`function ${name}(`);
  assert.ok(at >= 0, `function ${name} was not found`);
  const rest = PAGE.slice(at);
  const next = rest.slice(10).search(/\nfunction [A-Za-z]/);
  return next === -1 ? rest : rest.slice(0, next + 10);
}

test("the files are where this guard thinks they are", () => {
  assert.ok(PAGE.length > 100000 && BAR.length > 800 && FILTER.length > 1500);
  for (const name of ["PLSection", "BSSectionRows", "ProfitAndLoss", "BalanceSheet"]) assert.ok(fn(name).length > 300, name);
});

for (const [section, items] of [["PLSection", "item"], ["BSSectionRows", "b"]] as const) {
  test(`${section}: a caption's figure is the sum of ALL its accounts and the rows drawn are the filter's`, () => {
    const src = fn(section);
    assert.ok(new RegExp(`const totals = columnMaps\\.map\\(\\(m\\) => items\\.reduce\\(\\(s, ${items}\\) => s \\+ \\(m\\.get\\(${items}\\.account_id\\) \\?\\? 0\\), 0\\)\\)`).test(src),
      `${section}'s caption figure is no longer the sum of every account under it`);
    assert.ok(/const drawn = filterStatementRows\(items, filter\)/.test(src), `${section} does not draw the filter's rows (the statements' own, which keeps a derived line under every filter)`);
    assert.ok(/\{open && drawn\.map\(/.test(src), `${section} still draws every row`);
    assert.ok(!/drawn\.reduce|drawn\.filter\(|drawn\.length/.test(src), `${section} takes something from the rows drawn`);
    assert.ok(/filter = NO_FILTER/.test(src), `${section} is not unfiltered by default`);
  });
}

test("every call site passes the filter to its section, so no caption is drawn unfiltered by accident", () => {
  const calls = PAGE.match(/<(PLSection|BSSectionRows)\b[^>]*>/g) ?? [];
  assert.equal(calls.length, 5, "the number of section call sites changed; read them and update this count");
  for (const c of calls) assert.ok(/filter=\{filter\}/.test(c), `a section is drawn without the filter: ${c}`);
});

test("each statement keeps its own filter, drops it for the next client and shows the one bar once loaded", () => {
  for (const [name, prefix, accounts] of [["ProfitAndLoss", "pl", "unionAccounts"], ["BalanceSheet", "bs", "everyAccount"]] as const) {
    const src = fn(name);
    assert.ok(/const \[filter, setFilter\] = useState<TrialBalanceFilter>\(NO_FILTER\)/.test(src), `${name} has no filter state`);
    assert.ok(/useEffect\(\(\) => \{ setFilter\(NO_FILTER\); \}, \[clientId\]\)/.test(src), `${name}: a search is carried to the next client`);
    assert.ok(new RegExp(`<StatementFilterBar idPrefix="${prefix}" accounts=\\{${accounts}\\} filter=\\{filter\\} onChange=\\{setFilter\\} />`).test(src), `${name} does not show the bar`);
    assert.ok(new RegExp(`!loading && loaded && ${accounts}\\.length > 0 && \\(\\s*<StatementFilterBar`).test(src), `${name}: the bar can show before the statement or with nothing to filter`);
  }
  const bs = fn("BalanceSheet");
  assert.ok(/const everyAccount = \[\.\.\.assets, \.\.\.liabilities, \.\.\.equity\]/.test(bs), "the balance sheet's accounts for the bar are not all three groups");
});

test("the statement filter module adds up no money", () => {
  assert.ok(!/paise/i.test(FILTER) && !/Math\./.test(FILTER) && !/\.reduce\(/.test(FILTER));
});

test("the bar: two named controls, a type choice only for two or more types, a sentence that prints and controls that do not", () => {
  assert.ok(/<label htmlFor=\{`\$\{idPrefix\}-search`\} className="sr-only">Search accounts by code or name<\/label>/.test(BAR), "the search box has no name");
  assert.ok(/<label htmlFor=\{`\$\{idPrefix\}-type`\} className="sr-only">Account type<\/label>/.test(BAR), "the type choice has no name");
  assert.ok(/types\.length > 1 &&/.test(BAR), "a single-type statement shows a choice of one");
  assert.ok(/print:hidden">\s*<label/.test(BAR), "the controls are printed");
  assert.ok(/\{sentence && <p role="status" className="text-xs text-ps-label">\{sentence\}<\/p>\}/.test(BAR), "the sentence is hidden when printed or is not announced");
});

// ── rendered ───────────────────────────────────────────────────────────────────────────────────────

interface Row { account_id: string; account_code: string; account_name: string; account_type: string }
const accounts: Row[] = [
  { account_id: "a1", account_code: "1001", account_name: "Cash in hand", account_type: "Asset" },
  { account_id: "a2", account_code: "1002", account_name: "HDFC Bank", account_type: "Asset" },
  { account_id: "l1", account_code: "2001", account_name: "Sundry creditors", account_type: "Liability" },
  { account_id: "__surplus", account_code: "", account_name: "Brought-forward surplus", account_type: "Equity" },
];

function render(filter: { query: string; type: string }, rows: Row[] = accounts): string {
  const React = requireFromWeb("react");
  const { renderToStaticMarkup } = requireFromWeb("react-dom/server");
  const { StatementFilterBar } = loadModule<{ StatementFilterBar: unknown }>("components/accounting/StatementFilterBar");
  return renderToStaticMarkup(React.createElement(StatementFilterBar as never, { idPrefix: "t", accounts: rows, filter, onChange: () => undefined }));
}

test("rendered with no filter: the controls and no sentence", () => {
  const html = render({ query: "", type: "" });
  assert.ok(html.includes('id="t-search"') && html.includes('id="t-type"'), html);
  assert.ok(!html.includes("Showing"), "a sentence appears with no filter on");
  assert.ok(!html.includes(">Clear<"), "Clear shows with no filter on");
});

test("rendered with a search: the sentence counts the accounts and says the figures are whole", () => {
  const html = render({ query: "bank", type: "" });
  assert.ok(html.includes("Showing 1 of 3 accounts. Each caption&#x27;s figure and every total are for all 3, not only the ones shown.")
    || html.includes("Showing 1 of 3 accounts. Each caption's figure and every total are for all 3, not only the ones shown."), html);
  assert.ok(html.includes(">Clear<"), "no way back to the whole statement");
  assert.ok(html.includes('role="status"'), "the sentence is not announced");
});

test("rendered: the derived surplus row is not an account and is not counted", () => {
  assert.ok(render({ query: "x", type: "" }).includes("of 3 accounts"), "the derived row was counted as an account");
});

test("rendered: one type shows no type choice, two or more do", () => {
  const oneType = accounts.filter((a) => a.account_type === "Asset");
  assert.ok(!render({ query: "", type: "" }, oneType).includes('id="t-type"'), "a choice of one is offered");
  assert.ok(render({ query: "", type: "" }).includes('id="t-type"'), "the choice is missing for two types");
});

test("the sentence is the module's, singular for one account", async () => {
  const mod = loadModule<{ statementFilterNotice: (shown: number, total: number, f: { query: string; type: string }) => string | null }>("lib/accounting/trialBalanceFilter");
  assert.equal(mod.statementFilterNotice(0, 1, { query: "x", type: "" }), "Showing 0 of 1 account. Each caption's figure and every total are for all 1, not only the ones shown.");
  assert.equal(mod.statementFilterNotice(0, 5, { query: "", type: "" }), null);
});
