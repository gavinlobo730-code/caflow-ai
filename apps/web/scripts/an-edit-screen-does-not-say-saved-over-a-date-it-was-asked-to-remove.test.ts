// AN EDIT SCREEN DOES NOT SAY IT SAVED OVER A DATE IT WAS ASKED TO REMOVE (POST-A-388). Run with:
//   node --experimental-strip-types --test scripts/an-edit-screen-does-not-say-saved-over-a-date-it-was-asked-to-remove.test.ts
//
// THE DEFECT. Four edit screens sent a date box as `date || undefined` (the bank account's as `date || null`), and the PATCH routes read their body with `exclude_none`: a box the person
// emptied sent NOTHING, the stored date stayed as it was, and the screen said the record was saved. They were the shipping bill date of an export invoice, the Form 15CA date of a
// bill, a foreign supplier's no-PE declaration date and a bank account's opening-balance date. Each is evidence (customs' shipping bill, the remitter's Form 15CA, the signed
// declaration a nil withholding rests on, the date a balance is as at), so taking one away is not an everyday edit and the screens do not offer it: a date on file is REPLACED, and
// pressing Save over a box emptied is refused in a sentence beside the button (`lib/dates/removedDate.removedDateProblem`) and sends nothing. The server's own contract is plain and
// is not changed (an omitted date is unchanged, a blank one is refused on an update): it is the screen that must not claim what its request cannot do.
//
// THE RULE, per screen:
//  1. the sentence comes from `removedDateProblem(what, <the date on file>, <the box>)`, where the date on file is the record the form opened with (or, for the two editors that keep a
//     snapshot of what was last saved, the snapshot) and never a literal or the box itself;
//  2. it is DERIVED and said through the form's `useDateRefusal` latch, and is never copied into the form's error (`setError`, `setFormError`, `setMsg`), where it would stay after
//     the date was put back (the rule of the sixteenth slice: a sentence about what boxes hold is derived, an answer to an attempt is the form's error);
//  3. the Save handler refuses with `<latch>.refuse()` before it builds a request, and the latch's sentence is drawn;
//  4. the box's own sentence for text that is not a day comes first (an unreadable box hands up "" too): the derived value reads `<dates>.problems.<key>` and that key is one the screen
//     really watches, so the exclusion is not silently dead.
//
// POST-A-399 ADDED TWO MORE, FOR A DIFFERENT REASON: the due date of an invoice and of a bill. They are not evidence, but every document of the two kinds carries one (a create that names none
// resolves one) and the routes read a null as "not sent", so the screens refuse to save over one that was emptied instead of offering to clear it.
//
// WHAT THIS CANNOT SEE. Another edit screen with the same shape (a date box sent as `date || undefined` on a PATCH) is not found by it: the population is POST-A-388's four and POST-A-399's
// two, named. What each does in a browser is held by the date drive (`a-date-on-file-is-replaced-and-not-emptied-*`, three locale and zone pairs each), and the sentence's words by
// `lib/dates/removedDate.test.ts`.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

/** Source without comments or string-free commentary: a comment that explains the rule is not the rule. Template and string literals are kept (a quote inside a `//` is not a string). */
export function stripComments(src: string): string {
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

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

interface Form {
  name: string;
  file: string;
  /** The date as the sentence names it. */
  what: string;
  /** The expression for the date on file, as it is written in the call. */
  onFile: string;
  /** The state variable the box holds. */
  box: string;
  /** The derived sentence's name. */
  derived: string;
  /** The `useDateRefusal` result's name. */
  latch: string;
  /** The `useDateProblems` result the key is read from. */
  dates: string;
  /** The key `<dates>.problems.<key>` reads, which the box reports under. */
  key: string;
  /** What the latch is handed (the supplier form's also carries the box's own sentence). */
  latched: string;
  /** What the screen says beside the button for the latch. */
  drawn: RegExp;
  /** Where the Save handler asks. */
  asks: RegExp;
}

const FORMS: Form[] = [
  {
    name: "the invoice editor's shipping bill date", file: "components/invoices/InvoiceEditor.tsx", what: "The shipping bill date",
    onFile: "initialSnapshot.current.shippingBillDate", box: "shippingBillDate", derived: "shippingBillCleared", latch: "shippingBillRefusal", dates: "dates", key: "shippingBillDate",
    latched: "shippingBillCleared", drawn: /shippingBillRefusal\.shown\s*&&/, asks: /if \(shippingBillCleared\) \{[^}]*shippingBillRefusal\.refuse\(\);\s*return;\s*\}/,
  },
  {
    name: "the bill editor's Form 15CA date", file: "components/purchases/PurchaseBillEditor.tsx", what: "The Form 15CA date",
    onFile: "initialSnapshot.current.form15caFiledOn", box: "form15caFiledOn", derived: "form15caCleared", latch: "form15caRefusal", dates: "dates", key: "form15caFiledOn",
    latched: "form15caCleared", drawn: /form15caRefusal\.shown\s*&&/, asks: /if \(form15caCleared\) \{[^}]*form15caRefusal\.refuse\(\);\s*return;\s*\}/,
  },
  {
    name: "the supplier form's no-PE declaration date", file: "app/clients/[id]/purchases/page.tsx", what: "The no-PE declaration date",
    onFile: "editingVendor.no_pe_declaration_on", box: "noPeDeclarationOn", derived: "noPeCleared", latch: "noPeRefusal", dates: "noPeDates", key: "noPe",
    latched: "noPeDates.first ?? noPeCleared", drawn: /noPeRefusal\.shown/, asks: /if \(noPeDates\.first \?\? noPeCleared\) \{\s*noPeRefusal\.refuse\(\);\s*return;\s*\}/,
  },
  {
    name: "the bank account form's opening-balance date", file: "components/banking/AccountsPanel.tsx", what: "The opening balance date",
    onFile: "account?.opening_balance_date", box: "openingDate", derived: "openingCleared", latch: "openingRefusal", dates: "dates", key: "openingDate",
    latched: "openingCleared", drawn: /openingRefusal\.shown\s*&&/, asks: /if \(openingCleared\) \{[^}]*openingRefusal\.refuse\(\);\s*return;\s*\}/,
  },
  {
    name: "the invoice editor's due date", file: "components/invoices/InvoiceEditor.tsx", what: "The due date",
    onFile: "initialSnapshot.current.dueDate", box: "dueDate", derived: "dueDateCleared", latch: "dueDateRefusal", dates: "dates", key: "dueDate",
    latched: "dueDateCleared", drawn: /dueDateRefusal\.shown\s*&&/, asks: /if \(dueDateCleared\) \{[^}]*dueDateRefusal\.refuse\(\);\s*return;\s*\}/,
  },
  {
    name: "the bill editor's due date", file: "components/purchases/PurchaseBillEditor.tsx", what: "The due date",
    onFile: "initialSnapshot.current.dueDate", box: "dueDate", derived: "dueDateCleared", latch: "dueDateRefusal", dates: "dates", key: "dueDate",
    latched: "dueDateCleared", drawn: /dueDateRefusal\.shown\s*&&/, asks: /if \(dueDateCleared\) \{[^}]*dueDateRefusal\.refuse\(\);\s*return;\s*\}/,
  },
];

for (const f of FORMS) {
  const raw = read(f.file);
  const src = stripComments(raw);

  test(`${f.name}: the sentence is removedDateProblem over the date on file and the box, nothing else`, () => {
    assert.match(src, /import \{ removedDateProblem \} from "@\/lib\/dates\/removedDate";/, `${f.file} does not import removedDateProblem`);
    const call = new RegExp(`removedDateProblem\\(\\s*"${esc(f.what)}",\\s*${esc(f.onFile)},\\s*${esc(f.box)}[,)]`);
    assert.match(src, call, `${f.file} does not ask removedDateProblem("${f.what}", ${f.onFile}, ${f.box}): the date on file is the record the form opened with and the box is what it holds now`);
    assert.equal((src.match(new RegExp(`removedDateProblem\\(\\s*"${esc(f.what)}"`, "g")) ?? []).length, 1, `${f.file} asks removedDateProblem for "${f.what}" more than once`);
  });

  test(`${f.name}: the sentence is derived and latched, and never copied into the form's error`, () => {
    assert.match(src, new RegExp(`const ${f.derived} =`), `${f.file} has no derived sentence ${f.derived}`);
    assert.match(src, new RegExp(`const ${f.latch} = useDateRefusal\\(${esc(f.latched)}\\);`), `${f.file} does not hand ${f.latched} to useDateRefusal`);
    for (const copy of ["setError", "setFormError", "setMsg", "setMessage"]) {
      assert.doesNotMatch(src, new RegExp(`${copy}\\(\\s*${f.derived}\\b`), `${f.file} copies ${f.derived} into ${copy}: the sentence would stay after the date was put back`);
    }
  });

  test(`${f.name}: Save refuses before it builds a request, and the sentence is drawn`, () => {
    assert.match(src, f.asks, `${f.file}: the Save handler does not refuse over ${f.derived} with ${f.latch}.refuse()`);
    assert.match(src, f.drawn, `${f.file} never draws ${f.latch}.shown: the refusal would say nothing`);
  });

  test(`${f.name}: text that is not a day keeps the box's own sentence`, () => {
    const derived = src.slice(src.indexOf(`const ${f.derived} =`));
    const statement = derived.slice(0, derived.indexOf(";") + 1);
    assert.match(statement, new RegExp(`!${f.dates}\\.problems\\.${f.key}\\b`), `${f.file}: ${f.derived} does not leave text that is not a day to the box's own sentence (${f.dates}.problems.${f.key})`);
    assert.match(src, new RegExp(`${f.dates}\\.watch\\("${f.key}"`), `${f.file}: nothing reports under "${f.key}", so the exclusion above is dead`);
  });
}

test("the supplier form says the way out of a declaration, and the others offer no way out they do not have", () => {
  const supplier = stripComments(read("app/clients/[id]/purchases/page.tsx"));
  assert.match(supplier, /"untick the declaration if there is none"/, "the supplier form's sentence does not say how a declaration is withdrawn");
  for (const f of FORMS.filter((x) => x.derived !== "noPeCleared")) {
    assert.doesNotMatch(stripComments(read(f.file)), /removedDateProblem\([^)]*untick/, `${f.file} names a tick that is not on its form`);
  }
});

test("the sentence is one function with one set of words", () => {
  const lib = stripComments(read("lib/dates/removedDate.ts"));
  assert.match(lib, /on file can be corrected but not removed: \$\{way\}\./, "the sentence's words changed: the drive scenarios read them");
  assert.match(lib, /const way = orElse \? `enter the corrected date, or \$\{orElse\}` : "enter the corrected date";/, "the sentence no longer tells the person what to do, in both of its forms");
  // The words are written here and nowhere else in the app, so two screens cannot say it two ways.
  for (const f of FORMS) {
    assert.doesNotMatch(stripComments(read(f.file)), /can be corrected but not removed/, `${f.file} spells the sentence itself`);
  }
});

test("the stripper keeps strings and drops comments (the detector is tested on what it reads)", () => {
  assert.equal(stripComments('const a = "x // y"; // gone\nconst b = 1; /* gone */ const c = `t`;'), 'const a = "x // y"; \nconst b = 1;  const c = `t`;');
});
