// The Entries screen is a TABLE with a fixed Action column and ONE verb. Run with:
//   node --experimental-strip-types --test scripts/bank-entries-is-a-table.test.ts
//
// WHY THIS EXISTS
//     The queue was once a list of cards whose primary button sat at x≈625 on
//     one row and x≈1251 on the next; the eye had to re-find it on every line.
//     Nothing a test of BEHAVIOUR would notice was wrong — every button worked
//     — it was simply slow to use. The fix was one line per transaction and an
//     Action column that is a fixed strip you run straight down. This file is
//     what stops it drifting back, because "make the row a bit more flexible"
//     is a change nobody would flag in review.
//
//     The screen was rebuilt around ENTRIES on 2026-09-03
//     (docs/architecture/09-bank-entries.md): the draft is on the row, the
//     state is a stored column, and the verb is Pass. The properties below are
//     the same ones the old queue test held, re-pointed at the new files.
//
//     Later the same day the module was collapsed from five tabs to THREE —
//     Entries · Reconcile · Rules. Accounts was setup wearing a tab (it is a
//     panel and an Import button on Entries now), Bank Book was a report (it
//     is under Reports now), and the six state chips were the CA classifying
//     their own queue (three filters and one line of text now). Tests 8-11
//     hold that shape, because "just add a tab for it" is the drift.
//
// WHAT IS ASSERTED
//     1. The list renders the shared DataTable with the six columns, in order —
//        Spent and Received SEPARATE, and an Entry column that says what the
//        line is or is about to become (the column the old screen had removed,
//        which is why "where did the suggestion go" had no answer).
//     2. The action is rowActions — the fixed trailing column — and no column's
//        render carries a primary button.
//     3. ONE verb. Pass, on the row and in the modal. Not Post, not Match, not
//        Add, not Record: those were three words for one act.
//     4. The row offers no ranked candidate list; candidates live in the modal,
//        behind opening the line. The two ways out of an unanswerable line —
//        find the document, split it — are the largest controls in the modal.
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
const BANKING = path.join(__dirname, "..", "components", "banking");
const TAB = path.join(BANKING, "EntriesTab.tsx");
const MODAL = path.join(BANKING, "EntryDetailModal.tsx");
const SHELL = path.join(__dirname, "..", "app", "clients", "[id]", "bank", "page.tsx");
const REPORTS_INDEX = path.join(__dirname, "..", "app", "clients", "[id]", "reports", "page.tsx");
const BANK_BOOK_REPORT = path.join(__dirname, "..", "app", "clients", "[id]", "reports", "bank-book", "page.tsx");

const tab = () => fs.readFileSync(TAB, "utf8");
const modal = () => fs.readFileSync(MODAL, "utf8");

/** Every button's visible text. A <button …> tag spans lines and its
 *  attributes contain `=>`, so the tag cannot be matched with `[^>]*`; the
 *  label is instead the tail of the chunk before each </button>, after the
 *  last tag close (`">`, `}>` or `/>`). Both plain text and the string
 *  literals of a `{cond ? "…" : "Pass"}` expression count. */
function buttonLabels(src: string): string[] {
  const chunks = src.split("</button>").slice(0, -1);
  return chunks.flatMap((chunk) => {
    const cut = Math.max(chunk.lastIndexOf('">'), chunk.lastIndexOf("}>"), chunk.lastIndexOf("/>"));
    const tail = chunk.slice(cut + 2);
    const quoted = [...tail.matchAll(/"([^"]*)"/g)].map((q) => q[1]);
    const plain = tail.replace(/\{[\s\S]*?\}/g, " ").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    return quoted.concat(plain);
  }).map((x) => x.trim()).filter(Boolean);
}

test("the files exist and are not trivially short", () => {
  assert.ok(tab().length > 10_000, "EntriesTab.tsx is suspiciously short");
  assert.ok(modal().length > 8_000, "EntryDetailModal.tsx is suspiciously short");
});

test("the list is the shared DataTable, not a hand-rolled table or cards", () => {
  const s = tab();
  assert.match(s, /<DataTable\b/, "Entries must render the shared DataTable");
  assert.match(s, /columns=\{columns\}/, "it must pass its column set");
  assert.doesNotMatch(s, /<table\b/, "no hand-rolled <table> beside the DataTable");
});

test("the columns are the six, in order, with Entry present and Spent/Received separate", () => {
  const s = tab();
  const decl = s.slice(s.indexOf("const columns: Column<Entry>[]"));
  assert.ok(decl.length > 500, "the columns declaration came back empty");
  const body = decl.slice(0, decl.indexOf("\n  ];"));
  assert.ok(body.length > 400, "the columns body came back empty");
  const headers = [...body.matchAll(/header:\s*"([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(headers, ["Date", "Bank narration", "Entry", "Spent", "Received", "Status"],
    "the column set changed. Entry is the column that says what the line is or " +
    "is about to become — the one the old screen removed. Spent and Received are " +
    "SEPARATE on purpose. Action is rowActions, always last.");
});

test("the action is the fixed trailing column, and no column renders a primary button", () => {
  const s = tab();
  assert.match(s, /rowActions=\{actionCell\}/, "the row's one control must be rowActions");
  const decl = s.slice(s.indexOf("const columns: Column<Entry>[]"));
  const body = decl.slice(0, decl.indexOf("\n  ];"));
  assert.doesNotMatch(body, /<button/, "a column's render is producing a button");
});

test("one verb: Pass — on the row and in the modal; never Post, Match, Add or Record", () => {
  for (const [name, src] of [["EntriesTab", tab()], ["EntryDetailModal", modal()]] as const) {
    const labels = buttonLabels(src);
    assert.ok(labels.length > 5, `${name}: only ${labels.length} button labels matched`);
    assert.ok(labels.includes("Pass"), `${name}: expected "Pass" among ${JSON.stringify(labels)}`);
    for (const bad of ["Post", "Match", "Add", "Record"]) {
      assert.ok(!labels.includes(bad), `${name}: offers "${bad}" as a button label — the verb is Pass`);
    }
  }
});

test("the row offers no ranked candidate list; the modal does, behind opening the line", () => {
  const s = tab();
  assert.doesNotMatch(s, /\.suggestions\b/, "the row is reaching into ranked candidates — they belong in the modal");
  assert.doesNotMatch(s, /confidence_label/, "confidence badges belong to the modal's list, not the row");
  assert.match(modal(), /t\.suggestions/, "the modal must offer the candidates");
});

test("the two ways out of an unanswerable line are the largest controls in the modal", () => {
  const m = modal();
  for (const label of ["Find the ", "Split across several"]) {
    const at = m.indexOf(label);
    assert.ok(at > 0, `"${label}" is missing from the modal`);
    const btn = m.lastIndexOf("<button", at);
    const cls = m.slice(btn, at);
    assert.match(cls, /text-xs/, `"${label}" is back to a smaller type size than the rest of the modal`);
    assert.match(cls, /px-3 py-1\.5/, `"${label}" is back to a link-sized hit area`);
  }
});

test("the state is read, never decided, in the browser", () => {
  // The old screen kept its own copy of "which rows are confident"
  // (readyRow / confidentMatch). The database decides entry_state now, and a
  // browser-side reimplementation is exactly the drift 09-bank-entries.md
  // exists to prevent.
  for (const src of [tab(), modal()]) {
    assert.doesNotMatch(src, /\bconfidentMatch\b|\breadyRow\b|\breadyToAdd\b/,
      "a browser-side confidence rule is back");
  }
  assert.match(tab(), /t\.entry_state/, "the row must read the stored state");
});

/** The ids of an `id: "…"` array literal declared as `const NAME`. */
function idsOf(src: string, name: string): string[] {
  const at = src.indexOf(`const ${name}`);
  assert.ok(at >= 0, `${name} is not declared`);
  const decl = src.slice(at);
  const body = decl.slice(0, decl.indexOf("\n];"));
  assert.ok(body.length > 50, `the ${name} declaration came back empty`);
  return [...body.matchAll(/\bid:\s*"([^"]+)"/g)].map((m) => m[1]);
}

test("the module is three tabs — Entries · Reconcile · Rules — and nothing else", () => {
  const s = fs.readFileSync(SHELL, "utf8");
  assert.deepEqual(idsOf(s, "TABS"), ["entries", "reconcile", "rules"],
    "a tab came or went. Accounts is setup and lives behind Entries; Bank Book " +
    "is a report and lives under Reports. A new tab needs a reason a CA would " +
    "give, not a place to put something.");
});

test("accounts and statement import are reached from Entries, not from a tab", () => {
  const s = tab();
  assert.match(s, /from "@\/components\/banking\/AccountsPanel"/, "Entries must import the Accounts panel");
  assert.match(s, /<BankImportModal\b/, "Import statement must open the import modal directly");
  assert.match(s, /<BankAccounts\b/, "the Accounts panel must be rendered from Entries");
  assert.ok(buttonLabels(s).includes("Import statement"), "the toolbar must offer Import statement");
  assert.ok(!fs.existsSync(path.join(BANKING, "AccountsTab.tsx")), "AccountsTab.tsx is back — it is AccountsPanel.tsx");
});

test("Bank Book is a report under Reports, linked from Entries", () => {
  assert.match(fs.readFileSync(BANK_BOOK_REPORT, "utf8"), /<BankRegister\b/, "the report page must render the register");
  assert.match(fs.readFileSync(REPORTS_INDEX, "utf8"), /href:\s*"reports\/bank-book"/, "the Reports directory must list it");
  assert.match(tab(), /reports\/bank-book/, "Entries must link to it — a CA looking for the old tab needs a way there");
  assert.ok(!fs.existsSync(path.join(BANKING, "BankBookTab.tsx")), "BankBookTab.tsx is back — it is BankBook.tsx, rendered by the report page");
});

test("three filters — To do · Passed · Set aside — and the working states are a line of text", () => {
  const s = tab();
  assert.deepEqual(idsOf(s, "CHIPS"), ["to_do", "passed", "set_aside"],
    "the chips changed. The working states (ready / proposed / needs you) are " +
    "the WORKING line under To do, not chips — six chips made the CA classify " +
    "their own queue before they could work it.");
  assert.deepEqual(idsOf(s, "WORKING"), ["ready", "proposed", "needs_you"],
    "the working line lists the three open states in the order they are cleared");
});

test("settle runs on open, not on every filter/search/page change", () => {
  // settle() proposes for every undrafted line and then passes what trusted
  // rules drafted — a real sweep with its own network round trips, meant to
  // run once when the screen opens (and again after an import). If the
  // effect that fires it depends on the `settle` closure itself, it refires
  // on every bankAccountId/state/page/search change too, because settle
  // closes over loadCounts and reload, which close over those filters. That
  // produced a real burst of concurrent requests on the account-filter
  // dropdown — a transient 500 in production, traced to exactly this.
  const s = tab();
  const at = s.indexOf("const settle = useCallback(");
  assert.ok(at > 0, "settle is not declared");
  assert.match(s.slice(at), /useEffect\(\(\) => \{[\s\S]{0,200}settleRef\.current\(\);[\s\S]{0,40}\}, \[clientId\]\);/,
    "the effect that runs settle on open must depend on [clientId] alone, via a ref, " +
    "never on [settle] — settle's identity carries every filter it closes over.");
  assert.doesNotMatch(s.slice(at), /useEffect\(\(\) => \{ settle\(\); \}, \[settle\]\);/,
    "settle is wired straight to its own identity again — that re-runs the whole " +
    "propose-and-pass sweep on every filter change, not just a refetch");
});

test("the detail modal renders the row it was given; the fetch only enriches it", () => {
  // The modal used to render the single word "Loading…" until GET
  // /entries/{id} came back, with no error path and no retry — so a slow or
  // failed response left the CA staring at an empty box while the line's own
  // answer sat in the list behind it. The list already holds the whole row.
  const m = modal();
  assert.match(m, /initial\?: Entry \| null/, "the modal must accept the row the list already holds");
  assert.match(m, /useState<EntryDetail \| null>\(\(\) => \(initial \? fromRow\(initial\) : null\)\)/,
    "it must open FROM that row, not from null");
  assert.match(m, /enrich === "failed"/,
    "a failed enrichment must be a visible state, not silence");
  assert.match(m, /onClick=\{load\}/, "and it must offer a way to try again");
  assert.match(m, /enrich === "loading" && t\.suggestions\.length === 0/,
    "while the candidates are still coming, an empty list must not read as 'none found'");

  const tab = fs.readFileSync(TAB, "utf8");
  assert.match(tab, /initial=\{rows\.find\(\(r\) => r\.id === detailId\)\}/,
    "the list must hand the modal the row it already has");
});

test("a matched line names the document it settles, not just 'an invoice'", () => {
  // Every matched line on the page used to read "Receipt · against an
  // invoice" — one sentence for thirteen different documents, so nothing on
  // the row let a CA tell them apart or check a match without opening it.
  // The number is resolved server-side (one query per document type) and the
  // row prints it.
  const s = tab();
  assert.match(s, /matched_document_no: string \| null/,
    "the row type must carry the matched document's number");
  assert.match(s, /against \$\{noun\} \$\{t\.matched_document_no\}/,
    "and the Entry column must print it when it is there");
  assert.match(modal(), /t\.matched_document_no/,
    "the modal must name it too — it is the same question asked at the line");
});

test("a line can carry its receipt, and a stored document is never held by an expiring link", () => {
  // The backend has had attachments on a bank line since Tier 1.8, but the
  // module rebuilt in #395 dropped the UI while the design doc claimed it
  // kept it — so the receipt behind a coding had nowhere to live again.
  //
  // The trap this pins: the document store hands back a SIGNED url that dies
  // within the hour. Storing it would make the attachment a dead link exactly
  // when someone audits the coding, so what is stored is the document's id
  // and the link is minted at the moment it is opened.
  const m = modal();
  assert.match(m, /api\.documents\.upload\(form\)/, "the modal must upload into the firm's document store");
  assert.match(m, /attachments\.add\(txnId, \{ name: file\.name, document_id: documentId \}\)/,
    "and attach it BY ID — never by the signed url the upload returned");
  assert.doesNotMatch(m, /attachments\.add\([^)]*download_url/,
    "a signed, expiring url must never be what gets stored");
  assert.match(m, /api\.documents\.downloadUrl\(a\.document_id\)/,
    "opening a stored document must mint a fresh link");
  assert.match(m, /Supporting documents/, "the section must be on the line");

  assert.match(tab(), /<Paperclip\b/, "and the list must show which lines carry one");
});

test("picking a ledger changes the line at once, on the write's own answer", () => {
  // It used to cost four sequential round trips to Mumbai — the write, a full
  // re-read of the line, then the list's counts and its rows — with every
  // control disabled until the last landed. Only the write is needed:
  // banking_service.set_account returns account_id, category and gst_allowed
  // "so the screen can patch that one line instead of refetching the page",
  // and a ledger choice cannot change the candidates, the payee history or
  // the transfer scan that make the re-read expensive.
  const m = modal();
  const at = m.indexOf("<AccountLookup");
  assert.ok(at > 0, "the ledger picker is gone");
  const picker = m.slice(at, at + 600);
  assert.match(picker, /patch\("Couldn't book under that ledger"/,
    "the ledger picker must patch in place, not re-read the whole line");
  assert.doesNotMatch(picker, /act\("Couldn't book under that ledger"/,
    "act() re-reads the line and is for writes that change what it could be");

  const patchFn = m.slice(m.indexOf("async function patch("));
  assert.match(patchFn.slice(0, 900), /setT\(\(cur\) => \(cur \? \{ \.\.\.cur, \.\.\.optimistic \} : cur\)\)/,
    "the line must change on the click, before the server answers");
  assert.match(patchFn.slice(0, 900), /if \(seq !== writeSeq\.current\) return true/,
    "a superseded write's reply must not overwrite a later pick");
  assert.match(patchFn.slice(0, 1200), /setT\(before\)/, "and a refusal must put back what was there");

  // Nothing in the modal may block on the list behind it.
  assert.doesNotMatch(m, /await onChanged\(\)/,
    "the list's counts and rows are two more round trips; nothing the CA does next waits on them");
});

test("a write refreshes the list without blanking it", () => {
  // The shared table swaps its whole body for a skeleton whenever `loading`
  // is true. That is right for a first load and wrong for a re-read after a
  // write: the rows are already on screen and one of them just changed, so
  // blanking all of them into grey bars for the round trip reads as the page
  // breaking. A filter, page or search change still skeletons — there the
  // content genuinely is not there yet.
  const s = tab();
  assert.match(s, /const loadRows = useCallback\(async \(opts\?: \{ quiet\?: boolean \}\)/,
    "loadRows must be able to re-read quietly");
  assert.match(s, /if \(!opts\?\.quiet\) setLoading\(true\)/,
    "and only raise the skeleton when it is not a quiet re-read");
  assert.match(s, /loadRows\(\{ quiet: true \}\)/,
    "reload() is only ever called after a write, so it must be the quiet one");
  assert.match(s, /useEffect\(\(\) => \{ if \(clientId && clientId !== "_placeholder"\) loadRows\(\); \}/,
    "the first load and every filter change must still show the skeleton");
});

test("the kind comes from the server, and the label drops the word that says nothing", () => {
  // Receipt / Payment / Contra follows the CATEGORY, which follows the ledger
  // — picking a bank or cash account derives Transfer and makes the line a
  // Contra. That rule is domain/banking/entry.kind_for and it stays on the
  // server, so the modal may not compute a kind of its own while a pick is in
  // flight: it prints what the row says and lets the write's answer correct
  // it. Optimistically claiming one produced "Contra · Prepaid Expenses" on a
  // live client — the previous pick's kind beside the new account.
  const m = modal();
  const optimistic = m.match(/patch\("Couldn't book under that ledger",[\s\S]{0,200}?\)\)\} \/>/);
  assert.ok(optimistic, "the ledger picker must still patch in place");
  assert.doesNotMatch(optimistic[0], /\bkind:/,
    "the browser cannot derive the kind; only the server's answer may set it");
  assert.match(m, /const kind = KIND_LABEL\[t\.kind\]/,
    "the kind shown is the row's, which the write's response refreshes");

  // "Other" is what the derivation calls an ordinary ledger. It is not a fact
  // about the line, and the list already refuses to print it.
  assert.match(m, /sub: t\.category && t\.category !== "Other" \? t\.category : null/,
    "the modal must suppress the empty category word, as the list does");
});
