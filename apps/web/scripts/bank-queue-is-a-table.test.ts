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
/** The detail panel's source. It used to be DataTable's `expandedRow`; it is
 *  the centred modal now, opened from `detailId`. The tests below pin what the
 *  panel CONTAINS, which did not change when it moved — so they follow it
 *  rather than being deleted with the prop. */
function panelSource(s: string): string {
  const start = s.indexOf("const t = rows.find((r) => r.id === detailId);");
  assert.ok(start > 0, "the detail modal was not found — has it moved again?");
  const end = s.indexOf("{splitTxn && splitMode === \"ledgers\"}", start);
  const panel = s.slice(start, end > 0 ? end : start + 20_000);
  assert.ok(panel.length > 1_000, "the detail panel came back empty");
  return panel;
}

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
  assert.match(s, /columns=\{visibleQueueColumns\}/,
    "it must pass the column set below, minus any column hidden for this tab");
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
  const panel = panelSource(s);
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
  const panel = panelSource(s);

  // Reported as: "the split and the other option, it is so small I couldn't
  // notice them". They were text-[10px] px-2 py-0.5 among a dozen other 10px
  // things. A control nobody can find is a control that does not exist.
  for (const label of ["Find the ", "Split across several"]) {
    const at = panel.indexOf(label);
    assert.ok(at > 0, `"${label}" is missing from the detail panel`);
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

  const panel = panelSource(s);
  // The panel carries a LABELLED copy of the picker now, which is the point of
  // the modal — so "not in the panel" is no longer the invariant. What still
  // has to hold is that the row shows one without anything being opened, and
  // the column assertion above is what pins that. What must NOT come back is
  // the CATEGORY GATE, which is what actually hid it.
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
  const panel = panelSource(s);

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
  assert.match(s, /if \(!t\.gst_allowed\) \{/,
    "the GST cell must gate on gst_allowed — the flag posting_map.gst_split_" +
    "allowed sets, which is the SAME call the posting engine makes to refuse a " +
    "rate. Re-deriving the rule here (checking debit_paise, or the category " +
    "list) is how the screen ends up offering a control the server rejects. " +
    "Anchored on the brace: rateToSend's gate is `return \"\";` on one line, " +
    "and the looser form matched it too — so neutering the CELL left this green.");
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


// ── Undo, and the GST column saying why it is empty ──────────────────────────

test("Undo calls the endpoint that can actually undo a posting", () => {
  const s = queueSource();
  assert.match(s, /await api\.banking\.undoPost\(t\.id\);/,
    "undoRow called api.banking.unmatch, and bank_matching_service.unmatch " +
    "REFUSES a posted transaction with a 409. The button renders only on " +
    "posted rows, so every click failed. Undoing a posting means reversing " +
    "its journal and un-settling its document, which is what /undo does.");
  assert.doesNotMatch(s, /undoRow[\s\S]{0,400}api\.banking\.unmatch\(/,
    "unmatch clears a MATCH — a different operation that refuses posted rows");
});

test("the GST cell names the reason instead of showing a bare dash", () => {
  const s = queueSource();
  const decl = s.slice(s.indexOf('key: "gst"'));
  const cell = decl.slice(0, decl.indexOf("\n    },"));
  // The five reasons live in gstWhy() — one function, so the row's short label
  // and the modal's sentence can never be different answers. The vocabulary is
  // asserted there; the cell is asserted to USE it.
  const whole = fs.readFileSync(PAGE, "utf8");
  const whyDecl = whole.slice(whole.indexOf("function gstWhy("));
  const whyBody = whyDecl.slice(0, whyDecl.indexOf("\n}"));
  assert.ok(whyBody.length > 100, "gstWhy came back empty");
  for (const why of ["on the invoice", "per split", "not a supply", "pick a ledger", "control account"]) {
    assert.ok(whyBody.includes(why),
      `gstWhy must be able to say "${why}". A column of dashes reads as ` +
      "a broken feature — which is exactly how it was reported.");
  }
  assert.match(cell, /const why = gstWhy\(t\);/,
    "the cell must ASK gstWhy rather than repeat the ladder — two copies is how " +
    "the row and the modal start giving different answers");
  // Computing the reason is not showing it. Without this the cell could keep
  // all five strings and still render a dash — which is how the first negative
  // control for this test passed against code that had gone back to a dash.
  assert.match(cell, /title=\{GST_WHY_LONG\[why\]\}>\{why\}<\/span>/,
    "the reason has to be what the cell RENDERS, and the long form its tooltip");
  assert.match(panelSource(s), /GST_WHY_LONG\[gstWhy\(t\)\]/,
    "and the modal must explain it in full from the same answer");
});

test("the GST column is dropped on the tabs where nothing can be set", () => {
  const s = queueSource();
  assert.match(s, /const showGstColumn = status !== "done" && status !== "ignored";/,
    'Categorized is the LABEL of the tab whose id is "done" — naming it by ' +
    "label would leave the column on the very tab it was reported dead on.");
  assert.match(s, /queueColumns\.filter\(\(c\) => c\.key !== "gst" \|\| showGstColumn\)/,
    "the flag has to actually remove the column, not just be computed");
});


// ── the four changes the CA asked for ────────────────────────────────────────

test("coding a line patches that row instead of reloading the queue", () => {
  const s = queueSource();
  // Reported as "every time i choose or change the category the whole screen
  // loads again". codeToAccount ended in load(), which sets `loading` and
  // refetches the page from Mumbai — a cross-region round trip that tore down
  // and rebuilt fifty rows because one of them changed.
  const fn = s.slice(s.indexOf("async function codeToAccount"));
  const body = fn.slice(0, fn.indexOf("\n  }"));
  assert.doesNotMatch(body, /await load\(\)/,
    "codeToAccount must not refetch the whole page to show one row's ledger");
  assert.match(body, /patchRow\(t\.id, \{/, "it has to update the row it changed");
  assert.match(body, /gst_allowed: d\.gst_allowed/,
    "gst_allowed must be carried across, or the GST cell keeps saying 'pick a " +
    "ledger' after a ledger was picked — the contradiction that made reloading " +
    "look necessary in the first place");

  for (const name of ["applyRule", "applyHistory"]) {
    const f = s.slice(s.indexOf(`async function ${name}`));
    assert.doesNotMatch(f.slice(0, f.indexOf("\n  }")), /await load\(\)/,
      `${name} only codes the row too — it must not reload either`);
  }
});

test("the row asks one question; the rate is a read-out", () => {
  const s = queueSource();
  const decl = s.slice(s.indexOf('key: "gst"'));
  const cell = decl.slice(0, decl.indexOf("\n    },"));
  assert.doesNotMatch(cell, /<select/,
    "a rate select and an IGST checkbox squeezed beside the ledger picker is " +
    "what made the line look like a form. The row shows the rate; the modal sets it.");
  assert.doesNotMatch(cell, /type="checkbox"/, "same for the IGST toggle");
  assert.match(panelSource(s), /<select[\s\S]{0,900}GST_RATE_OPTIONS\.map/,
    "and the modal is where the rate is actually chosen");
});

test("clicking a line opens the modal, and Add still posts straight away", () => {
  const s = queueSource();
  assert.match(s, /onRowClick=\{\(t\) => setDetailId\(t\.id\)\}/,
    "a click opens the centred detail modal");
  assert.doesNotMatch(s, /expandedRow=\{/,
    "the stacked expanded row is what the modal replaced");
  // The CA chose this: Add on a coded row posts, it does not open a dialogue.
  // With 47 lines to clear, a confirmation per row is 47 extra round trips
  // through a modal.
  const cellFn = s.slice(s.indexOf("const actionCell ="));
  const action = cellFn.slice(0, cellFn.indexOf("\n  };"));
  assert.match(action, /if \(!isMatch && !readyToAdd\(t\)\) \{ setDetailId\(t\.id\); return; \}/,
    "a line that cannot be posted yet must OPEN, not sit disabled behind a tooltip");
  assert.match(action, /postRow\(t\);/,
    "and a ready line posts straight away rather than opening a confirmation");
  assert.doesNotMatch(action, /disabled=\{busy\[t\.id\] \|\| \(!isMatch && !readyToAdd\(t\)\)\}/,
    "the dead-end disabled state is what opening the modal replaced");
});

test("the ledger list is reordered by use, and never shortened", () => {
  const s = queueSource();
  assert.match(s, /const orderedAccounts = useMemo/, "the ordering has to exist");
  const fn = s.slice(s.indexOf("const orderedAccounts = useMemo"));
  const body = fn.slice(0, fn.indexOf("\n  }, ["));
  assert.doesNotMatch(body, /\.filter\(/,
    "ORDER, never filter: a ledger this client has not used yet is often " +
    "exactly why the picker was opened, so nothing may be removed from it");
  assert.match(body, /\.sort\(/, "it reorders");
  const decl = s.slice(s.indexOf("const queueColumns"));
  const cols = decl.slice(0, decl.indexOf("\n  ];"));
  assert.match(cols, /accounts=\{orderedAccounts\}/,
    "the ROW's picker gets the ordered list — asserting on the whole component " +
    "was satisfied by the modal's copy while the row still had the raw chart");
  assert.match(panelSource(s), /accounts=\{orderedAccounts\}/,
    "and so does the modal's, or the same list is ordered differently in two places");
});

// ── The bulk path: one ledger, many lines ───────────────────────────────────
//
// WHY THESE EXIST
//     The screen had a "— Bulk category —" dropdown in the toolbar. It called
//     categorize() with a CATEGORY and nothing else — the very word the row had
//     stopped asking for, because the category follows from the ledger
//     server-side (domain/banking/account_category). For the three auto-counter
//     categories the posting engine could still derive its own counter account,
//     so those lines did become recordable. For the other eight it wrote a word,
//     left the line with no ledger and therefore unpostable, and cleared the
//     selection as though the work were done.
//
//     It is a "Set ledger" action now, opening the same two-field modal the
//     single line uses. These tests pin the three things that made it correct
//     rather than merely different: it asks for a LEDGER, it does not touch
//     lines a ledger cannot be set on, and it will not put one GST rate across
//     a selection where some line cannot carry one.

/** The bulk modal's source. Sliced, because every control in it — the account
 *  picker, the rate select, the IGST box — also exists on the row or in the
 *  detail modal, and an assertion made against the whole component would be
 *  satisfied by those copies while this modal was deleted. */
function bulkModalSource(s: string): string {
  const start = s.indexOf("{bulkRows && (() => {");
  assert.ok(start > 0, "the bulk modal was not found — has it moved?");
  const end = s.indexOf("{/* The detail modal:", start);
  assert.ok(end > start, "could not find the end of the bulk modal");
  const modal = s.slice(start, end);
  assert.ok(modal.length > 1_500, `the bulk modal came back at ${modal.length} chars`);
  return modal;
}

/** Source with BLOCK comments removed. The invariants below are about what
 *  the screen DOES, and the comments explaining what a control replaced
 *  legitimately quote the old control by name — a scan of the raw source finds
 *  those quotes and reports the deleted control as still present. Line
 *  comments are left alone so a "//" inside a string literal survives. */
function codeOnly(s: string): string {
  const out = s.replace(/\/\*[\s\S]*?\*\//g, " ");
  assert.ok(out.length > 5_000 && out.length < s.length,
    "the comment strip produced nothing usable");
  return out;
}

/** applyBulkLedger's body, for the same reason. */
function bulkApplySource(s: string): string {
  const start = s.indexOf("async function applyBulkLedger() {");
  assert.ok(start > 0, "applyBulkLedger was not found");
  const end = s.indexOf("\n  /** The single action behind Match / Add", start);
  assert.ok(end > start, "could not find the end of applyBulkLedger");
  const body = s.slice(start, end);
  assert.ok(body.length > 1_000, `applyBulkLedger came back at ${body.length} chars`);
  return body;
}

test("GST is off the row by default, and one click away in the Columns menu", () => {
  const s = queueSource();
  const decl = s.slice(s.indexOf("const queueColumns"));
  const body = decl.slice(0, decl.indexOf("\n  ];"));

  // Scoped to the GST column's own entry, not the whole column set: asserting
  // "defaultHidden appears somewhere in queueColumns" would be satisfied by any
  // other column acquiring it, while GST came back onto the row.
  const at = body.indexOf('key: "gst"');
  assert.ok(at > 0, "the GST column is gone entirely — it should be hidden, not deleted");
  const entry = body.slice(at, body.indexOf("},", at));
  assert.match(entry, /defaultHidden:\s*true/,
    "the GST column must be default-hidden. On the tab where the work happens " +
    "every cell of it reads \"pick a ledger\" until a ledger is chosen, which " +
    "is placeholder text occupying a column; the rate is set in the detail " +
    "modal, which has room to say which section it is claimed under.");
  assert.doesNotMatch(entry, /hideable:\s*false/,
    "default-hidden AND unhideable would make the column unreachable — the " +
    "Columns menu is how a CA who wants to eyeball rates before recording " +
    "gets it back");
});

test("changing a persisted default came with a persistKey bump", () => {
  const s = queueSource();
  // hiddenColumns is persisted to localStorage, and a saved "nothing hidden"
  // wins over a column's own defaultHidden on hydration. Without a new key,
  // anyone who had already used this screen would keep the GST column and
  // never see the change — the default would be live in the source and dead in
  // every browser that mattered.
  assert.doesNotMatch(s, /persistKey="bank\.categorize"/,
    "the table is still on the pre-change persistKey, so saved prefs will " +
    "override the new column default for every existing user");
  assert.match(s, /persistKey="bank\.categorize\.v\d+"/,
    "the queue's persistKey must carry a version suffix, so the next change " +
    "to a persisted default can be shipped the same way");
});

test("the bulk control asks for a ledger, not the category the row stopped asking for", () => {
  const s = queueSource();

  const code = codeOnly(s);
  assert.doesNotMatch(code, /bulkCategory/,
    "the bulk-category control is back. The category follows from the ledger " +
    "server-side; setting it alone leaves eight of the eleven categories with " +
    "no counter account and the line still unpostable");
  assert.doesNotMatch(code, /Bulk category/,
    "the toolbar still offers a bulk CATEGORY picker");

  const actions = s.slice(s.indexOf("const queueBulkActions"));
  const body = actions.slice(0, actions.indexOf("\n  ];"));
  assert.ok(body.length > 200, "the queueBulkActions body came back empty");
  const labels = [...body.matchAll(/label:\s*"([^"]+)"/g)].map((m) => m[1]);
  assert.ok(labels.length >= 3, `only ${labels.length} bulk labels matched`);
  assert.ok(labels.includes("Set ledger"),
    `the bulk actions must offer "Set ledger", got: ${JSON.stringify(labels)}`);
  assert.ok(!labels.includes("Apply category"),
    "\"Apply category\" is back among the bulk actions");
});

test("the bulk modal carries the same two fields as the single line", () => {
  const s = queueSource();
  const modal = bulkModalSource(s);

  // \b so a renamed near-namesake cannot satisfy it, and the value binding so
  // the row's own picker cannot: this must be the BULK one.
  assert.match(modal, /<AccountLookup\b/,
    "the bulk modal must offer the chart-of-accounts picker");
  assert.match(modal, /value=\{bulkAccountId\}/,
    "the bulk modal's picker must be bound to the bulk selection's own ledger");
  assert.match(modal, /GST_RATE_OPTIONS\.map/,
    "the bulk modal must offer the same rate list as the line — a second list " +
    "would be a second answer to the same question");
});

test("a bulk ledger is not written over an answer already given", () => {
  const s = queueSource();
  const at = s.indexOf("const bulkEligible");
  assert.ok(at > 0, "bulkEligible was not found");
  const fn = s.slice(at, s.indexOf(";\n", s.indexOf("filter(", at)));
  assert.ok(fn.length > 100, "bulkEligible came back empty");

  // Each of the three exclusions asserted separately. A single regex over the
  // whole predicate would stay green if two of the three were dropped.
  assert.match(fn, /match_status !== "posted"/,
    "a posted line must be excluded — it needs Undo, not a new ledger");
  assert.match(fn, /match_status !== "ignored"/,
    "an excluded line must be excluded — it needs putting back first");
  assert.match(fn, /!t\.is_split/,
    "a split line already HAS its ledgers; one written over the allocation " +
    "would silently replace an answer the CA has already given");
});

test("one rate is never applied across a selection that cannot all take one", () => {
  const s = queueSource();
  const at = s.indexOf("const bulkGstOffered");
  assert.ok(at > 0, "bulkGstOffered was not found");
  const fn = s.slice(at, s.indexOf(";\n", at));
  assert.ok(fn.length > 80, "bulkGstOffered came back empty");

  // EVERY, not some. A selection mixing a bank charge with a line that settles
  // an invoice would otherwise take one rate across both, and the invoice line
  // already carries its own tax — the same tax counted twice (CGST Act s.16).
  assert.match(fn, /\.every\(/,
    "the rate must be offered only when EVERY selected line could carry one");
  assert.doesNotMatch(fn, /\.some\(/,
    "\"some line can take a rate\" is the wrong test — it is the lines that " +
    "CANNOT that decide this");
  assert.match(fn, /gstWhy\(t\) === "pick a ledger"/,
    "the only blocker a ledger fixes is the missing ledger itself; a line " +
    "blocked on the invoice, the split or a transfer never becomes eligible " +
    "whatever ledger is chosen, and must keep the rate off the whole selection");
});

test("the bulk apply sets the ledger first, and reports every line it did not record", () => {
  const s = queueSource();
  const body = bulkApplySource(s);

  const setAt = body.indexOf("setTransactionAccount");
  const postAt = body.indexOf("postTransaction");
  assert.ok(setAt > 0, "the bulk apply never sets a ledger");
  assert.ok(postAt > 0, "the bulk apply never records anything");
  assert.ok(setAt < postAt,
    "the ledger has to be written BEFORE the post — the posting engine reads " +
    "it from the row, so posting first would record the line uncoded");

  // The server's verdict, not a rule re-derived here: a line that turns out to
  // refuse the rate is left in the queue rather than quietly recorded gross,
  // which would put a different answer on one line of a batch than the rest.
  // `data?.gst_allowed`, not bare `gst_allowed`: the response TYPE annotation
  // in this function also spells the field, so the loose version stayed green
  // with the read itself replaced by a hard-coded `true` — verified by making
  // exactly that change and watching the test pass.
  assert.match(body, /data\?\.gst_allowed/,
    "the apply must read the server's own verdict back after setting the ledger, " +
    "rather than assume the rate is allowed");
  assert.match(body, /if \(rate !== "" && !allowed\)/,
    "the verdict must GATE the post: a line the server says cannot carry the " +
    "rate is left in the queue, not recorded gross while the rest are split");
  assert.match(body, /status: "skipped"/,
    "lines that were selected but not recorded must be reported, not dropped — " +
    "a selection of eight that records six has to say what became of the other two");
  assert.match(body, /status: "failed"/,
    "a rejected line must be reported per line: one failure must not strand " +
    "the other seven, and the reader has to be told WHICH failed");
});
