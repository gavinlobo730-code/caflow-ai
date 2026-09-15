/**
 * ACC-14 — the browser must not decide what an opening document is.
 *
 * The reconciliation between a party's opening balance and the documents behind
 * it is the answer this feature exists to give, and it is
 * `domain/accounting/opening_documents.py`'s. A copy of it here is a second
 * place for it to be wrong, and this one is what the CA reads.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const TAB = "components/accounting/OpeningBalancesTab.tsx";
const PAGE = "app/clients/[id]/accounting/page.tsx";
const API = "lib/api/index.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the difference is the server's sentence, never recomputed here", () => {
  const src = code(TAB);
  assert.match(src, /r\.sentence/,
    "the server says what the difference means; the browser renders it");
  assert.match(src, /r\.agrees/);
  // A second arithmetic here is the drift. The one subtraction that IS allowed
  // is the summary tile, which restates a total the server already sent.
  assert.doesNotMatch(src, /difference_paise\s*[-+*/]/,
    "the per-party difference is computed server-side");
  assert.doesNotMatch(src, /documents_paise\s*!==\s*/,
    "whether a party agrees is the server's answer, not a comparison here");
});

test("the amount goes through the one money parser", () => {
  /* CLAUDE.md: nothing whose name ends in _paise may be built with a numeric
     coercion or a multiplication by 100. An opening balance typed as
     "1,25,000" must not become one rupee. */
  const src = code(TAB);
  assert.match(src, /paiseFromRupeeInput\(/);
  assert.doesNotMatch(src, /parseFloat/);
  assert.doesNotMatch(src, /\*\s*100/);
});

test("the tab says the document posts no journal", () => {
  /* It is the BREAKUP of a balance the ledger already carries. A CA who thinks
     it posts will expect the balance to move and will enter it twice. */
  const src = code(TAB);
  // BOTH places, asserted separately. An alternation would pass on a commit
  // that dropped either one — and the two are read at different moments: the
  // header before the CA starts, the drawer footer as they are about to save.
  assert.match(src, /Nothing is posted/,
    "the header, before the CA starts entering");
  assert.match(src, /No journal is posted/,
    "the drawer footer, where they are about to save");
});

test("the outstanding figure is asked for, not the face value", () => {
  /* A document part-paid before the migration is carried at its BALANCE: that
     is what ages and what the control account holds. */
  const src = code(TAB);
  assert.match(src, /Still outstanding/);
  assert.match(src, /not the document/i);
});

test("the tab holds no statute of its own", () => {
  const src = code(TAB);
  // The section 194 sentence is the server's, rendered verbatim.
  assert.match(src, /kinds\?\.section_194_aggregate/);
  assert.doesNotMatch(src, /194C|s\.194|section 194 aggregate is/i);
  // And no Rule 46(b) check on a number the other system issued: not the
  // sixteen-character limit, not the character set. `size={16}` on an icon is
  // not a length limit, which is why the check names the two real spellings.
  assert.doesNotMatch(src, /maxLength=\{?16/);
  assert.doesNotMatch(src, /document_no[\s\S]{0,80}\.length\s*>\s*16/);
  assert.ok(!src.includes("[A-Z0-9-/]"), "no character-set check either");
});

test("the tab is reachable from the client accounting screen", () => {
  const src = code(PAGE);
  assert.match(src, /\{ id: "opening-balances", label: "Opening Balances" \}/);
  assert.match(src, /tab === "opening-balances" && \(/);
});

test("the api layer carries shapes and no statute", () => {
  const src = code(API);
  const start = src.indexOf("openingDocuments: {");
  assert.ok(start > 0, "the namespace exists");
  const ns = src.slice(start, start + 1800);
  assert.match(ns, /\/api\/opening-documents\/kinds/);
  assert.match(ns, /\/api\/opening-documents\/reconciliation/);
  assert.match(ns, /method: "DELETE"/);
  // Creating one is a POST; the list and the reconciliation are reads.
  assert.doesNotMatch(ns, /reconciliation[\s\S]{0,200}method: "POST"/);
});


test("an account opened twice is shown, with both figures and no difference", () => {
  /* The masters and the trial-balance import post into separate journal
     families that never reconcile against each other. A bank balance entered on
     the bank master AND carried on an imported trial balance is posted twice,
     and the balance sheet is out by exactly it. Which of the two is the mistake
     is the CA's answer, so the panel renders the server's sentence and offers
     no netted figure to post. */
  const src = code(TAB);
  assert.match(src, /api\.openingDocuments\.reconciliation\(clientId\)/,
    "the panel is fed by the endpoint that compares the two journal families");
  assert.match(src, /double_openings/);
  assert.match(src, /doubles\.map\(\(d\) => <p key=\{d\.account_id\}>\{d\.sentence\}<\/p>\)/);
  assert.doesNotMatch(src, /master_paise\s*[-+]/,
    "no netted difference — which posting is the mistake is the CA's answer");
  assert.match(src, /Reverse whichever/,
    "and it must say that nothing is undone automatically");
});
