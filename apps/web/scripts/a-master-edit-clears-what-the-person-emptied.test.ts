// A PARTY OR BANK-ACCOUNT EDIT CLEARS A SOFT BOX THE PERSON EMPTIED, REFUSES AN EMPTIED TAX IDENTIFIER, AND NEVER SAYS "SAVED" OVER THE OLD VALUE (POST-A-399, second slice). Run with:
//   node --experimental-strip-types --test scripts/a-master-edit-clears-what-the-person-emptied.test.ts
//
// THE DEFECT. The vendor screens and the bank-account screen sent an emptied box as `x || undefined` (or `|| null`, which the route dropped), so the stored value stayed and the
// screen said the record was saved; the customer screen sent "" and the route stored "", which for a GSTIN silently turned every document already issued to the customer into an
// unregistered recipient's in every return not yet filed. The routes now clear what the models name in CLEARABLE and refuse an emptied identifier over a stored one
// (`tests/test_an_emptied_box_on_a_party_or_bank_account_edit.py` on the API side).
//
// THE RULE, per screen, in the code that builds the edit's request:
//  1. each clearable key is sent through `editedText` or `editedChoice` (directly, or through a local `edited` that calls `editedChoice`), never as `x || undefined` or `x || null`;
//  2. a tax identifier a return reads (a party's GSTIN and state code, a vendor's PAN and foreign tax number) is never sent through either and never as `|| null`: an empty
//     one is left out, and the screen calls `removedIdentifierProblem` for each such identifier it shows before anything is sent, which is the server's sentence (a customer's
//     PAN and TAN are not among them: no return reads them, so they are clearable and go through rule 1);
//  3. the bank account's ledger link is never sent as `|| null` on the edit, and an emptied link on file is refused on the screen.
// WHAT THIS CANNOT SEE: what the request carries in a browser (no drive is written for these four screens), and a new master edit screen, which is not on the list below.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

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

const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

interface Screen {
  name: string;
  file: string;
  /** Where the request that edits is built: from this text to the end marker. */
  from: string;
  to: string;
  clearable: string[];
  identifiers: { key: string; label: string }[];
}

const SCREENS: Screen[] = [
  {
    name: "the customer form",
    file: "components/customers/CustomerFormModal.tsx",
    from: '`/api/customers/${existing.id}`, "PATCH"',
    to: 'await apiCall("/api/customers/", "POST"',
    // A customer's PAN and TAN are cleared, not refused: no return reads either off a customer, so the refusal's reason would be untrue of them.
    clearable: ["email", "phone", "city", "state", "credit_limit_paise", "pan", "tan"],
    identifiers: [{ key: "gstin", label: "GSTIN" }, { key: "state_code", label: "state code" }],
  },
  {
    name: "the client's vendor form",
    file: "app/clients/[id]/purchases/page.tsx",
    from: "const fields = {",
    to: "const result = editingVendor",
    clearable: ["email", "phone", "residential_status", "gst_registration_status", "country_of_residence", "section_195_nature_of_income",
                "non_resident_payee_class", "treaty_rate_bps"],
    identifiers: [{ key: "gstin", label: "GSTIN" }, { key: "pan", label: "PAN" }, { key: "tax_identification_number", label: "tax identification number" }],
  },
  {
    name: "the firm's supplier screen",
    file: "app/accounting/suppliers/page.tsx",
    from: "const body: VendorWrite = {",
    to: "try {",
    clearable: ["gst_registration_status"],
    identifiers: [{ key: "gstin", label: "GSTIN" }, { key: "pan", label: "PAN" }],
  },
  {
    name: "the bank-account form",
    file: "components/banking/AccountsPanel.tsx",
    from: "api.banking.updateBankAccount(account!.id, {",
    to: "api.banking.createBankAccount(",
    clearable: ["ifsc"],
    identifiers: [],
  },
];

function region(s: Screen): string {
  const src = read(s.file);
  const a = src.indexOf(s.from);
  assert.ok(a >= 0, `${s.name}: the request that edits is not found (${s.from})`);
  const b = src.indexOf(s.to, a + s.from.length);
  assert.ok(b > a, `${s.name}: the end of the request that edits is not found (${s.to})`);
  return src.slice(a, b);
}

/** The text of `key: <value>` up to the next top-level comma of the object literal. */
function valueOf(body: string, key: string): string | null {
  const m = new RegExp(`(?:^|[\\s,{])${key}\\s*:`).exec(body);
  if (!m) return null;
  let i = m.index + m[0].length;
  let depth = 0;
  const start = i;
  for (; i < body.length; i += 1) {
    const c = body[i];
    if ("([{".includes(c)) depth += 1;
    else if (")]}".includes(c)) { if (depth === 0) break; depth -= 1; }
    else if (c === "," && depth === 0) break;
  }
  return body.slice(start, i).trim();
}

for (const s of SCREENS) {
  test(`${s.name} sends each clearable box through the helper that sends null for one the person emptied`, () => {
    const body = region(s);
    for (const key of s.clearable) {
      const v = valueOf(body, key);
      assert.ok(v, `${s.name}: ${key} is not in the request`);
      assert.match(v!, /\bedited(Text|Choice)?\(/, `${s.name}: ${key} is sent as ${v}, which does not say "clear" for a box the person emptied`);
      assert.ok(!/\|\|\s*(undefined|null)\s*$/.test(v!), `${s.name}: ${key} is sent as ${v}`);
    }
    const src = read(s.file);
    assert.match(src, /from "@\/lib\/forms\/editedValue";/, `${s.name}: the helpers are not imported from lib/forms/editedValue`);
    if (/\bedited\(/.test(body)) assert.match(src, /const edited = [^\n]*editedChoice\(/, `${s.name}: the local edited() is not editedChoice`);
  });

  if (s.identifiers.length) {
    test(`${s.name} never sends a tax identifier empty, and refuses one emptied over a value on file in the server's words`, () => {
      const body = region(s);
      const src = read(s.file);
      for (const { key, label } of s.identifiers) {
        const v = valueOf(body, key);
        if (v !== null) {
          assert.ok(!/\bedited/.test(v), `${s.name}: ${key} is an identifier and is never cleared by an edit`);
          assert.ok(!/\|\|\s*null\b/.test(v) && !/^null$/.test(v), `${s.name}: ${key} is sent as ${v}, which the route reads as a removal`);
        }
        assert.match(src, new RegExp(`removedIdentifierProblem\\("${label}",`), `${s.name}: an emptied ${label} on file is not refused on the screen`);
      }
    });
  }
}

test("the customer form does not refuse an emptied PAN or TAN, which no return reads off a customer", () => {
  const src = read(SCREENS[0].file);
  for (const label of ["PAN", "TAN"]) {
    assert.doesNotMatch(src, new RegExp(`removedIdentifierProblem\\("${label}",`), `the customer form refuses an emptied ${label}, saying a return reads it, which none does`);
  }
});

test("the bank-account form keeps its ledger link and refuses emptying one on file", () => {
  const body = region(SCREENS[3]);
  assert.match(valueOf(body, "coa_account_id") ?? "", /^coaId \|\| undefined$/, "the edit sends an emptied ledger link as something other than nothing");
  assert.match(read("components/banking/AccountsPanel.tsx"), /if \(editing && account\?\.coa_account_id && !coaId\)/, "an emptied ledger link on file is not refused");
});

test("the firm's supplier screen shows a credit limit of 0 as 0, so a Save does not read it as no limit", () => {
  const src = read("app/accounting/suppliers/page.tsx");
  assert.match(src, /credit_limit_rs: v\.credit_limit_paise != null \?/, "a limit of 0 opens as a blank box, which the route now clears to 'no limit'");
});
