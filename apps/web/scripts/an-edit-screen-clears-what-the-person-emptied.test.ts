// AN EDIT SCREEN CLEARS A SOFT BOX THE PERSON EMPTIED, AND NEVER SAYS "SAVED" OVER A BOX IT LEFT ALONE (POST-A-399, first slice). Run with:
//   node --experimental-strip-types --test scripts/an-edit-screen-clears-what-the-person-emptied.test.ts
//
// THE DEFECT. An edit screen sent a soft box as `value.trim() || undefined`. `JSON.stringify` drops an undefined key, and the PATCH routes read their body as "what was sent", so a note or a
// reference the person had EMPTIED reached the server as nothing: the stored value stayed, and the screen said the document was updated. The routes now take an explicit null as "clear this"
// for the few SOFT free-text fields a model names (`models.clearable.patch_dict`, held on the API side by `tests/test_an_emptied_box_on_an_edit_clears_the_stored_value.py`), and the
// screens say it with `lib/forms/editedValue.editedText`:
//
//   - text in the box              -> the text;
//   - emptied, and a value on file -> null (the person took it away);
//   - empty, and nothing on file   -> nothing (a field the screen never showed is never erased).
//
// THE RULE, per edit screen, inside the branch that edits (not the one that creates):
//  1. each soft text key is sent as `key: editedText(<its box>, <the record on file>)` and never as `x || undefined`, which sends nothing for an emptied box;
//  2. the record on file is what the form opened with (or last saved): `initialSnapshot.current.<field>`, `softOnFile.<field>` (the same snapshot, bound once) or `existing.<field>`. It is
//     never a literal and never the box itself, because either would make every emptied box look like one that was always empty;
//  3. a DATE (the due date) and the EVIDENCE of a document (the bill number, the attached copy of the supplier's invoice, the Form 15CA / 15CB references) are NOT sent through
//     `editedText`: every invoice and bill carries a due date, so the screen refuses to save over one that was emptied (`dueDateCleared`, held by
//     `an-edit-screen-does-not-say-saved-over-a-date-it-was-asked-to-remove.test.ts`), and evidence is not an everyday edit (POST-A-388 refuses its dates on the screen; its texts are the
//     remainder of POST-A-399);
//  4. the create branch is unchanged, except that the two SALES note editors now send the note they always showed a box for.
// The request that carries the edit must also keep a null in its body (`JSON.stringify`, no replacer).
//
// WHAT THIS CANNOT SEE. A new edit screen with the same shape is not found by it: the population is the six document editors the first slice converted, named. The API side keeps a list
// of the PATCH handlers that read their body with a null-dropping read of their own (`tests/test_a_patch_handler_that_cannot_clear_a_field_is_named_and_the_list_only_shrinks.py`: 27 today),
// so most of the rest of the population is counted there; six more hand their body to a helper or a service that drops the nulls, and the scan cannot see through a call, so that test names
// them instead (`_NOT_SEEN`). What each screen sends in a browser is held by the drive (`cleared-boxes`, and the due date rows of `dates`).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

/** Source without comments (a comment that explains the rule is not the rule). Strings and template literals are kept. */
function stripComments(src: string): string {
  let out = "";
  let i = 0;
  let quote: string | null = null;
  while (i < src.length) {
    const c = src[i];
    const n = src[i + 1];
    if (quote) {
      out += c;
      if (c === "\\") { out += n ?? ""; i += 2; continue; }
      if (c === quote) quote = null;
      i += 1;
      continue;
    }
    if (c === "/" && n === "/") { while (i < src.length && src[i] !== "\n") i += 1; continue; }
    if (c === "/" && n === "*") { i += 2; while (i < src.length && !(src[i] === "*" && src[i + 1] === "/")) i += 1; i += 2; continue; }
    if (c === '"' || c === "'" || c === "`") quote = c;
    out += c;
    i += 1;
  }
  return out;
}

interface Soft {
  /** The request key. */
  key: string;
  /** The state variable the box holds. */
  box: string;
  /** The field of the record on file, as it follows its root. */
  field: string;
}

interface Editor {
  name: string;
  file: string;
  /** Where the branch that EDITS begins, and the text that ends it (the create branch follows). */
  from: string;
  to: string;
  /** How many PATCH bodies the branch builds (a draft and an issued one, or a locked and an unlocked one). */
  bodies: number;
  /** The soft text keys, each sent through editedText. */
  soft: Soft[];
  /** The root a record on file may be read from in this editor. */
  roots: string[];
  /** Keys that are dates or evidence and must NOT be sent through editedText. */
  kept: string[];
  /** The create branch: from this text to the end of the POST body. */
  createFrom: string;
  /** Whether the create branch sends the note (every note editor now does). */
  createSendsNotes?: boolean;
}

const EDITORS: Editor[] = [
  {
    name: "the sales invoice editor", file: "components/invoices/InvoiceEditor.tsx", from: "if (patchId) {", to: "} else {\n        const created", bodies: 2,
    soft: [{ key: "reference_no", box: "referenceNo", field: "referenceNo" }, { key: "notes", box: "notes", field: "notes" }],
    roots: ["initialSnapshot.current."], kept: ["due_date", "credit_days"], createFrom: "const created = await apiCall(",
  },
  {
    name: "the purchase bill editor", file: "components/purchases/PurchaseBillEditor.tsx", from: "if (isEdit && existing) {", to: "} else {", bodies: 2,
    soft: [{ key: "our_reference", box: "ourReference", field: "ourReference" }, { key: "notes", box: "notes", field: "notes" }],
    roots: ["softOnFile."], kept: ["due_date", "document_url", "bill_no", "form_15ca_ack_no", "form_15ca_filed_on", "form_15cb_udin"], createFrom: "const result = await apiCall(",
  },
  {
    name: "the sales credit note editor", file: "components/sales/SalesCreditNoteEditor.tsx", from: "if (isEdit && existing) {", to: "} else {", bodies: 2,
    soft: [{ key: "notes", box: "notes", field: "notes" }], roots: ["existing."], kept: [], createFrom: "const result = await apiCall(", createSendsNotes: true,
  },
  {
    name: "the sales debit note editor", file: "components/sales/SalesDebitNoteEditor.tsx", from: "if (isEdit && existing) {", to: "} else {", bodies: 2,
    soft: [{ key: "notes", box: "notes", field: "notes" }], roots: ["existing."], kept: [], createFrom: "const result = await apiCall(", createSendsNotes: true,
  },
  {
    name: "the purchase debit note editor", file: "components/purchases/DebitNoteEditor.tsx", from: "if (isEdit && existing) {", to: "} else {", bodies: 2,
    soft: [{ key: "notes", box: "notes", field: "notes" }], roots: ["existing."], kept: ["document_url"], createFrom: "const result = await apiCall(", createSendsNotes: true,
  },
  {
    name: "the purchase credit note editor", file: "components/purchases/PurchaseCreditNoteEditor.tsx", from: "if (isEdit && existing) {", to: "} else {", bodies: 2,
    soft: [{ key: "notes", box: "notes", field: "notes" }], roots: ["existing."], kept: ["document_url"], createFrom: "const result = await apiCall(", createSendsNotes: true,
  },
];

function editBranch(e: Editor): string {
  const src = stripComments(read(e.file));
  const start = src.indexOf(e.from);
  assert.ok(start >= 0, `${e.name}: the branch that edits was not found (${e.from})`);
  const end = src.indexOf(e.to, start + e.from.length);
  assert.ok(end > start, `${e.name}: the end of the branch that edits was not found`);
  return src.slice(start, end);
}

function createBranch(e: Editor): string {
  const src = stripComments(read(e.file));
  const start = src.indexOf(e.createFrom, src.indexOf(e.from));
  assert.ok(start >= 0, `${e.name}: the request that creates was not found (${e.createFrom})`);
  const end = src.indexOf("token,", start);
  assert.ok(end > start, `${e.name}: the end of the request that creates was not found`);
  return src.slice(start, end);
}

/** Every `key: editedText(a, b)` in the source, with its two arguments split at the top-level comma. */
function editedCalls(src: string): { key: string; box: string; onFile: string }[] {
  const out: { key: string; box: string; onFile: string }[] = [];
  const re = /\b([A-Za-z_0-9]+)\s*:\s*editedText\(/g;
  for (let m = re.exec(src); m; m = re.exec(src)) {
    let depth = 1;
    let comma = -1;
    let i = re.lastIndex;
    for (; i < src.length; i += 1) {
      const c = src[i];
      if (c === "(") depth += 1;
      else if (c === ")") { depth -= 1; if (depth === 0) break; }
      else if (c === "," && depth === 1 && comma < 0) comma = i;
    }
    assert.ok(comma > 0 && i < src.length, `an editedText call for ${m[1]} is not two arguments`);
    out.push({ key: m[1], box: src.slice(re.lastIndex, comma).trim(), onFile: src.slice(comma + 1, i).trim() });
  }
  return out;
}

for (const e of EDITORS) {
  test(`${e.name} sends a soft box the person emptied as null, and an untouched empty one as nothing`, () => {
    const branch = editBranch(e);
    assert.ok(branch.includes('"PATCH"'), `${e.name}: the branch found is not the one that PATCHes`);
    for (const s of e.soft) {
      const calls = editedCalls(branch).filter((c) => c.key === s.key);
      assert.equal(calls.length, e.bodies, `${e.name}: ${s.key} is sent through editedText ${calls.length} times and the branch builds ${e.bodies} request bodies`);
      assert.ok(!new RegExp(`\\b${s.key}\\s*:[^,\\n]*\\|\\|\\s*undefined`).test(branch), `${e.name}: ${s.key} is still sent as "x || undefined", which sends nothing for an emptied box`);
    }
    assert.match(stripComments(read(e.file)), /import \{ editedText \} from "@\/lib\/forms\/editedValue";/, `${e.name}: editedText is not imported from lib/forms/editedValue`);
  });

  test(`${e.name} judges an emptied box against the record on file, never against a literal or the box itself`, () => {
    const branch = editBranch(e);
    for (const s of e.soft) {
      for (const c of editedCalls(branch).filter((x) => x.key === s.key)) {
        assert.equal(c.box, s.box, `${e.name}: ${s.key} is sent from ${c.box}, but its box is ${s.box}`);
        const root = e.roots.find((r) => c.onFile.startsWith(r));
        assert.ok(root, `${e.name}: ${s.key} is judged against ${c.onFile}, which is not the record on file (${e.roots.join(" or ")})`);
        assert.equal(c.onFile.slice(root!.length), s.field, `${e.name}: ${s.key} is judged against ${c.onFile}, which is another field's value`);
      }
    }
  });

  if (e.kept.length) {
    test(`${e.name} neither clears a date nor the evidence of the document`, () => {
      const branch = editBranch(e);
      for (const key of e.kept) {
        assert.ok(!new RegExp(`\\b${key}\\s*:\\s*edited[A-Za-z]*\\(`).test(branch), `${e.name}: ${key} is a date or evidence of the document and is not cleared by an edit (the screen refuses an emptied date; evidence is POST-A-388's and the rest of POST-A-399's)`);
      }
    });
  }

  if (e.createSendsNotes) {
    test(`${e.name} sends the note a new document is given`, () => {
      assert.match(createBranch(e), /\bnotes:\s*notes\.trim\(\)\s*\|\|\s*undefined/, `${e.name}: the request that creates leaves out the note the form has a box for`);
    });
  }
}

test("the bill editor binds the record on file once, to the snapshot the form opened with", () => {
  const src = stripComments(read("components/purchases/PurchaseBillEditor.tsx"));
  assert.equal((src.match(/const softOnFile = /g) ?? []).length, 1, "the record on file is bound once");
  assert.match(src, /const softOnFile = initialSnapshot\.current;/, "the record on file is not the snapshot the form opened with");
});

test("the invoice editor judges a draft against what the draft last held: the snapshot is moved to what was saved", () => {
  const src = stripComments(read("components/invoices/InvoiceEditor.tsx"));
  assert.ok((src.match(/initialSnapshot\.current = snapshotOfWhatWasSaved\(\);/g) ?? []).length >= 2, "a draft that was saved and is edited again is judged against what it held at the save, not what it held when the form opened");
});

test("nothing outside the six editors sends a date or a piece of evidence through editedText", () => {
  const roots = ["components", "app", "lib"];
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const ent of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
      const rel = `${dir}/${ent.name}`;
      if (ent.isDirectory()) { if (ent.name !== "node_modules") walk(rel); continue; }
      if (!/\.(ts|tsx)$/.test(ent.name) || /\.test\.ts$/.test(ent.name)) continue;
      const src = stripComments(read(rel));
      if (!src.includes("editedText(")) continue;
      for (const c of editedCalls(src)) {
        if (/(_date|_on|_at|date)$/i.test(c.key) || /^(credit_days|bill_no|document_url|form_15\w+|gstin|pan|tan)$/i.test(c.key)) offenders.push(`${rel}: ${c.key}`);
      }
    }
  };
  for (const r of roots) walk(r);
  assert.deepEqual(offenders, [], "editedText is for a soft free-text box; a date is corrected and not emptied, and evidence and identity are decided one field at a time");
});

test("the request that carries the edit keeps a null in its body", () => {
  const src = stripComments(read("lib/invoices/shared.ts"));
  assert.match(src, /body:\s*body\s*\?\s*JSON\.stringify\(body\)\s*:\s*undefined/, "apiCall must serialise the body as it is: a replacer that drops nulls would turn a clear into nothing");
  assert.ok(!/JSON\.stringify\(\s*body\s*,/.test(src), "apiCall serialises its body with a replacer");
});

test("the helper decides the three cases in one place and offers no way to clear a date", () => {
  const src = stripComments(read("lib/forms/editedValue.ts"));
  assert.match(src, /export function editedText\(/);
  assert.ok(!/export function edited(Terms|Whole|Date)\b/.test(src), "the helper offers a way to clear a date or a pair of terms: the screen refuses it instead");
});
