// The Categorize queue is a TABLE with a fixed Action column. Run with:
//   node --experimental-strip-types --test scripts/bank-queue-is-a-table.test.ts
//
// WHY THIS EXISTS
//     The queue was a list of cards. Each card stacked a name line, a date line
//     and a control row, and the control row laid out left-to-right from
//     whatever text preceded it — so the primary button sat at x≈625 on a
//     matched row and x≈1251 on the next one. The eye had to re-find the button
//     on every line. Nothing was broken in any way a test of BEHAVIOUR would
//     notice: every button worked, and every row could be cleared. It was
//     simply slow to use, and the person using it could not say why.
//
//     The fix was to copy what QuickBooks does — one line per transaction, and
//     an Action column that is a fixed vertical strip you run straight down.
//     This file is what stops it drifting back, because "make the row a bit
//     more flexible" is a change nobody would flag in review.
//
//     The queue was later migrated onto the shared DataTable, so it could have
//     search, column visibility and a page-size control without a second
//     implementation of each. The PROPERTIES below are unchanged; where they
//     are asserted moved, from hand-written <table> markup to the `columns`
//     array and `rowActions` that produce it.
//
// WHAT IS ASSERTED
//     1. The queue renders a <table>, with the expected column headers in
//        order — including Spent and Received as SEPARATE money columns.
//     2. The action button is in the LAST cell of the row. That is the whole
//        point: a button in the Description or Category cell moves with the
//        text beside it.
//     3. The vocabulary is two verbs. "Post" was our internal word for what
//        happens after a click and it confused the reader, who saw Post, Add
//        and Match for two distinct acts.
//
//     Each assertion is preceded by a check that the parse found anything at
//     all, because a selector that silently matches nothing passes every test
//     after it.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "bank", "page.tsx");

/** The BankMatchQueue component's source, from its declaration to the next
 *  top-level declaration. Everything asserted here is inside it. */
function queueSource(): string {
  const src = fs.readFileSync(PAGE, "utf8");
  const start = src.indexOf("function BankMatchQueue(");
  assert.ok(start > 0, "BankMatchQueue not found — has the component been renamed?");
  const rest = src.slice(start + 1);
  const nextTop = rest.search(/\n(?:function|const|interface|export) /);
  return nextTop > 0 ? rest.slice(0, nextTop) : rest;
}

test("the parse finds the queue component and it is not trivially short", () => {
  const s = queueSource();
  assert.ok(s.length > 5_000,
    `queueSource() returned ${s.length} chars — the slice is wrong, and every ` +
    "assertion below would pass against an empty string");
});

test("the queue is a table, not a list of cards", () => {
  const s = queueSource();
  assert.match(s, /<DataTable\b/,
    "the Categorize queue must render the shared DataTable — a hand-rolled " +
    "list is what it replaced, and rebuilding one loses search, column " +
    "visibility, export and the page-size control with it");
  assert.match(s, /columns=\{queueColumns\}/, "it must pass the column set below");
});

test("the columns are the seven, in order, with Spent and Received separate", () => {
  const s = queueSource();
  const decl = s.slice(s.indexOf("const queueColumns"));
  assert.ok(decl.length > 500, "the queueColumns declaration came back empty");
  const body = decl.slice(0, decl.indexOf("\n  ];"));
  assert.ok(body.length > 400, "the queueColumns body came back empty");

  const headers = [...body.matchAll(/header:\s*"([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(headers,
    ["Date", "Description", "Payee", "Ledger or match", "GST", "Spent", "Received"],
    "the column set changed. Spent and Received are SEPARATE on purpose — " +
    "money out and money in are the two things the eye separates first. " +
    "GST sits between the ledger and the amounts because it is a property OF " +
    "the amount, and it is a column at all because it used to be buried in the " +
    "opened row, offered on debits only. Action is not among them: it is " +
    "rowActions, which DataTable always renders last, which is what keeps the " +
    "button in a fixed strip.");
});

test("the action button is in the fixed trailing column, and nowhere else", () => {
  const s = queueSource();
  assert.match(s, /rowActions=\{\(t\) => actionCell\(t\)\}/,
    "the Add/Match button must be rowActions — DataTable renders that column " +
    "last and at a fixed width, which is what stops the button moving from " +
    "row to row the way it did when the table was hand-rolled");

  // And it must not ALSO be produced by a column's render, which would put a
  // second primary action wherever that column happens to sit.
  const decl = s.slice(s.indexOf("const queueColumns"));
  const body = decl.slice(0, decl.indexOf("\n  ];"));
  assert.doesNotMatch(body, /isMatch \? "Match" : "Add"/,
    "a primary action button is being rendered inside a column");
});

test("two verbs, not three — the queue no longer says Post", () => {
  const s = queueSource();
  // Button LABELS only. The word legitimately appears in identifiers
  // (postRow), in status values ("posted") and in prose explaining which side
  // of a transfer posts the journal — none of those are what the reader
  // clicks, so scan the text between <button …> and </button> and nothing else.
  const labels = [...s.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)]
    .map((m) => m[1])
    // Strip JSX expressions down to just their string literals: the action
    // button's text is `{busy ? "…" : isMatch ? "Match" : "Add"}`.
    .flatMap((body) => [...body.matchAll(/"([^"]*)"/g)].map((q) => q[1])
      .concat(body.replace(/\{[\s\S]*?\}/g, " ").trim()))
    .map((x) => x.trim())
    .filter(Boolean);

  assert.ok(labels.length > 5,
    `only ${labels.length} button labels matched — the scan is not finding them`);
  assert.ok(labels.includes("Match") && labels.includes("Add"),
    `expected both verbs among the labels, got: ${JSON.stringify(labels)}`);
  assert.ok(!labels.includes("Post"),
    'the queue offers "Post" as a button label. Match links this line to a ' +
    "document that already exists; Add creates the entry from a category. " +
    '"Post" is what happens next, not a third thing the reader chooses.');
});

test("the queue offers ONE match, not a ranked list", () => {
  const s = queueSource();

  // WHY. A ₹1,00,000 payment on a client with ten open bills was offered five
  // candidates, every one "short by" a five-figure sum at 40–50% confidence,
  // each with its own orange button. That is not a suggestion, it is a wall —
  // and it grows with the client's open documents, so it is worst exactly
  // where a CA most needs the screen to be quiet.
  //
  // The ONE confident candidate (exact amount, >=90%) still surfaces, in the
  // Category-or-match column with a single Match button. Anything else is
  // reached deliberately, through "Find the invoice" or "Split across
  // several" — which is a search, not a list the screen pushes at you.
  // Asserted on the PANEL, and as "does not reach the suggestions at all"
  // rather than "does not contain this exact expression". My first version
  // matched `sugg[t.id].map(` literally and a re-added list written with
  // optional chaining walked straight past it — verified by adding one back
  // and watching the test stay green.
  const panel = s.slice(s.indexOf("expandedRow={"), s.indexOf("rowActions={"));
  assert.ok(panel.length > 1_000, "the expanded-row panel came back empty");
  assert.doesNotMatch(panel, /\bsugg\b/,
    "the expanded row is reaching into the ranked candidates again — the one " +
    "confident match belongs on the LINE, and everything else behind a search");
  assert.doesNotMatch(s, /confidence_label|confColor/,
    "confidence badges belong to the ranked list, which this screen no longer shows");

  // And the one match is still offered — removing the list must not have
  // removed the match with it.
  assert.match(s, /confidentMatch\(t\)/,
    "the single confident match must still be computed and offered");
});

test("the two ways out of an unanswerable row are the largest controls in the panel", () => {
  const s = queueSource();
  const panel = s.slice(s.indexOf("expandedRow={"), s.indexOf("rowActions={"));
  assert.ok(panel.length > 1_000, "the expanded-row panel came back empty");

  // Reported as: "the split and the other option, it is so small I couldn't
  // notice them". They were text-[10px] px-2 py-0.5 among a dozen other 10px
  // things. A control nobody can find is a control that does not exist.
  for (const label of ["Find the ", "Split across several"]) {
    const at = panel.indexOf(label);
    assert.ok(at > 0, `"${label}" is missing from the expanded row`);
    // The button opening tag is the nearest one before the label.
    const btn = panel.lastIndexOf("<button", at);
    const cls = panel.slice(btn, at);
    assert.match(cls, /text-xs/,
      `"${label}" is back to a smaller type size than the rest of the panel`);
    assert.match(cls, /px-3 py-1\.5/,
      `"${label}" is back to a link-sized hit area`);
  }
});


test("the ledger picker is on the ROW, and is not gated behind a category", () => {
  const s = queueSource();

  // WHY. The account picker DID exist — inside the opened row, rendered only
  // once a Category had been chosen and only for categories that are not
  // auto-counter. A reader who had not chosen a category saw no way to name an
  // account at all, and reported it as missing. It was not missing; it was
  // behind a gate nothing told them about.
  //
  // The column now holds the ledger itself, and the category is derived from it
  // server-side (domain/banking/account_category). Asserted on the COLUMN, so
  // that moving the picker back into the panel fails here.
  const decl = s.slice(s.indexOf("const queueColumns"));
  const body = decl.slice(0, decl.indexOf("\n  ];"));
  assert.ok(body.length > 400, "the queueColumns body came back empty");
  // \b so a renamed near-namesake (<AccountLookupX …>) does not satisfy it —
  // the first version of this assertion did, which made the control it defends
  // removable without a failure.
  assert.match(body, /<AccountLookup\b/,
    "the Ledger column must render the chart-of-accounts picker on the line");
  assert.match(body, /onChange=\{\(id\) => codeToAccount\(t, id\)\}/,
    "picking a ledger must write it through — a draft held in the browser is " +
    "lost the moment the reader pages, searches or reloads");

  const panel = s.slice(s.indexOf("expandedRow={"), s.indexOf("rowActions={"));
  assert.ok(panel.length > 1_000, "the expanded-row panel came back empty");
  assert.doesNotMatch(panel, /<AccountLookup|— Account —/,
    "the ledger picker is back inside the opened row, where it cannot be seen " +
    "until someone opens it");
  assert.doesNotMatch(panel, /AUTO_COUNTER_CATEGORIES\.has/,
    "the panel is gating a control on the category again — that ordering is " +
    "the bug: the category now FOLLOWS the ledger, it does not unlock it");
});

test("a split line is shown as a split, not offered a ledger picker", () => {
  const s = queueSource();
  const decl = s.slice(s.indexOf("const queueColumns"));
  const body = decl.slice(0, decl.indexOf("\n  ];"));

  // A split row carries a null category and a null account_id, exactly like an
  // untouched one. Without this branch the column would offer a picker over an
  // allocation already made, and the first ledger chosen would replace it.
  // The literal guard, not just a mention of the flag: `if (false && t.is_split)`
  // contains the flag, sits in the right place, and reaches the picker anyway.
  const at = body.indexOf("if (t.is_split) {");
  assert.ok(at > 0, "the Ledger column must recognise an already-split row");
  assert.ok(at < body.indexOf("<AccountLookup"),
    "the split check must come BEFORE the picker, or the picker wins");
});

test("one Split button, with the choice of what to split across inside it", () => {
  const s = queueSource();
  const panel = s.slice(s.indexOf("expandedRow={"), s.indexOf("rowActions={"));

  // Splitting across LEDGERS and splitting across DOCUMENTS are both real. They
  // were one button labelled "several" whose behaviour was always documents, so
  // the ledger split — complete in the backend since migration 256 — had no
  // route through the UI and zero call sites.
  const opens = [...panel.matchAll(/onClick=\{\(\) => (openSplit|openSettle)\(t\)\}/g)]
    .map((m) => m[1]);
  assert.deepEqual([...new Set(opens)], ["openSplit"],
    "the row must offer ONE split entry point; the ledger/document choice is a " +
    "switch inside the editor, not a second button competing for the same word");
  assert.match(s, /splitMode === "ledgers"[\s\S]{0,200}<SplitAcrossLedgersModal/,
    "the ledger split editor must actually be rendered");
  assert.match(s, /modeSwitch=\{splitModeSwitch\}/,
    "both editors must show the same switch, in the same place");
});


// ── GST is on the line, both directions, and only where the server allows ────

test("the GST control reads the server's verdict rather than re-deriving it", () => {
  const s = queueSource();
  assert.match(s, /if \(!t\.gst_allowed\) return <span/,
    "the GST cell must gate on gst_allowed — the flag posting_map.gst_split_" +
    "allowed sets, which is the SAME call the posting engine makes to refuse a " +
    "rate. Re-deriving the rule here (checking debit_paise, or the category " +
    "list) is how the screen ends up offering a control the server rejects. " +
    "Anchored on the <span it returns: the looser form was also satisfied by " +
    "rateToSend's gate, so neutering the CELL left this test green.");
});

test("the GST control is not restricted to money going out", () => {
  const s = queueSource();
  const decl = s.slice(s.indexOf('key: "gst"'));
  const cell = decl.slice(0, decl.indexOf("\n    },"));
  assert.ok(cell.length > 200, "the gst column body came back empty");
  assert.doesNotMatch(cell, /debit_paise\s*>\s*0/,
    "gating the rate on a debit is the restriction this change removed: money " +
    "arriving can be an outward supply (a banked cash sale) whose tax is " +
    "output tax under CGST Act s.9. Direction picks the ACCOUNTS server-side, " +
    "not whether a rate may be stated at all.");
});

test("the category is no longer a question the row asks", () => {
  const s = queueSource();
  assert.doesNotMatch(s, /onChange=\{\(e\) => categorize\(t\.id, e\.target\.value\)\}/,
    "the per-row Category override is gone: the ledger decides the category " +
    "server-side (domain/banking/account_category), a matched invoice or bill " +
    "decides it by itself (_MATCH_DEFAULT_CATEGORY), and picking the other " +
    "bank account is what makes a line a Transfer. Putting the dropdown back " +
    "asks for an answer the row already has.");
});


test("a rate the server would refuse is never sent with the post", () => {
  const s = queueSource();
  assert.match(s, /if \(!t\.gst_allowed\) return "";/,
    "postRow falls back to suggested_gst_rate_bps, and a rule can propose a " +
    "rate on a row the posting engine refuses one on. Without this gate the " +
    "proposal is sent anyway and Add fails with a message about a control the " +
    "reader cannot see, because the cell correctly rendered nothing.");
  assert.equal((s.match(/const rate = rateToSend\(t\);/g) ?? []).length, 2,
    "both send sites — the single row and the bulk apply — must go through it; " +
    "the bulk one is exactly where an unseen rate does the most damage");
});
