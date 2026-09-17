// A screen records WHICH SECTION a supplier is withheld under, never at what
// rate. (PUR-06, which the audit also filed as TDS-13 — one defect, two ids.)
//
// Run with:
//   node --experimental-strip-types --test scripts/a-screen-does-not-set-a-vendors-tds-rate.test.ts
//
// WHAT WAS WRONG
//     `vendors.tds_rate_bps` exists and nothing in the withholding engine
//     reads it. `services/vendor_tds.resolve_resident_tds` takes the rate from
//     `domain/tds/section_rates.py` — FY-versioned, per section, with the
//     individual/company split and s.206AA's no-PAN floor — so a rate typed on
//     a vendor master was shown to the CA, stored, and then not used. The CA
//     sees 2% on the supplier and 10% on the bill, and neither screen explains
//     the other.
//
//     A rate BELOW the section's has exactly one lawful source: a s.197
//     certificate. s.197(1) requires the Assessing Officer to issue it for a
//     specified amount and a specified period not exceeding the financial
//     year, and s.197(2) obliges the payer to deduct at the certified rate
//     until it is cancelled — four facts. A bare percentage on a master
//     expresses none of them, which is why `domain/tds/lower_deduction.py`
//     says in its own docstring that PUR-06 deleted the box rather than
//     honouring it.
//
// WHY THE GUARD, AND NOT JUST THE DELETION
//     It was deleted once, from the client workspace's Vendors form, and
//     `/accounting/suppliers` still had its own copy for another day —
//     complete with a "TDS Rate" column in the list, so the stale figure was
//     on screen without opening anything. Two independent copies of one
//     control is the shape this repository keeps finding. A third fails here.
//
// THE OTHER HALF IS STRUCTURAL
//     `VendorWrite` in lib/api/index.ts no longer declares `tds_rate_bps`, so
//     TypeScript refuses a screen that tries. This file states the rule for
//     the PostgREST path, which has no type to refuse it — and asserts the
//     type stays narrow, since widening it again would make the compiler stop
//     helping.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
}

/** Every .ts/.tsx under app/, components/ and lib/. */
function sources(): { rel: string; body: string }[] {
  const out: { rel: string; body: string }[] = [];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name)) {
        out.push({ rel: path.relative(WEB, p), body: code(fs.readFileSync(p, "utf8")) });
      }
    }
  };
  for (const d of ["app", "components", "lib"]) walk(path.join(WEB, d));
  return out.sort((a, b) => a.rel.localeCompare(b.rel));
}

// A BILL'S OWN `tds_rate_bps` IS A DIFFERENT COLUMN AND IS FINE TO READ.
// `purchase_bills.tds_rate_bps` and `purchase_payments.tds_rate_bps` record the
// rate the ENGINE applied — computed, stored on the document, and rendered by
// the bill drawer and the TDS register. Only a WRITE onto the VENDOR master is
// the defect.
//
// THE RULE IS THE VALUE, NOT A LIST OF FILES. Two create paths legitimately
// send the key: the client workspace's Vendors form and the CSV importer, both
// sending a LITERAL 0, which is the point — an explicit zero is what stops a
// rate surviving from an earlier edit or an earlier version of the importer.
// So a literal `0` passes and anything else fails, and a third create path
// needs no entry here. That is deliberately not an allowlist: this defect has
// already appeared in two independent screens, and a list of the two that
// exist today is a list that has to be remembered.
const ASSIGNMENT = /\btds_rate_bps\s*\??\s*:\s*([^,;\n}]*)/g;

/** A type annotation, not a value — `tds_rate_bps: number | null;`. */
const TYPE_POSITION = /^(number|string|boolean)(\s*\|\s*(null|undefined|number))*$/;

test("no screen writes a rate onto the vendor master", () => {
  const offenders: string[] = [];
  for (const { rel, body } of sources()) {
    if (rel === path.join("lib", "api", "index.ts")) continue;   // checked below
    // Only a file that is about `vendors` — a purchase bill's own rate is the
    // engine's answer and is read and rendered all over the app.
    if (!/vendors|VendorWrite|BuiltVendor|supplier/i.test(body)) continue;
    for (const m of body.matchAll(ASSIGNMENT)) {
      const value = m[1].trim();
      if (value === "0") continue;                 // explicitly not recorded
      if (TYPE_POSITION.test(value)) continue;     // an interface field
      offenders.push(`${rel}: tds_rate_bps: ${value}`);
    }
  }
  assert.deepEqual(offenders, [], (
    "these set a TDS rate on a supplier. Nothing in apps/api reads " +
    "`vendors.tds_rate_bps` — the rate comes from the section's own entry in " +
    "domain/tds/section_rates.py for the bill's financial year — so the figure " +
    "is shown, stored and then not used. A lower rate is a s.197 certificate, " +
    "recorded on the client's TDS compliance screen with its amount and its " +
    `period. A literal 0 is the one value allowed:\n  ${offenders.join("\n  ")}`
  ));
});

test("the two create paths that do send it send a literal zero", () => {
  // A vacuity floor. The test above passes trivially if the key stops being
  // written anywhere at all — which would be fine — but it also passes if the
  // `vendors|supplier` filter above stops matching, which would not be. These
  // two are the paths the rule was written around.
  const zeros = sources().filter(({ body }) => /\btds_rate_bps\s*:\s*0\b/.test(body))
                         .map(({ rel }) => rel);
  assert.deepEqual(zeros.sort(), [
    "app/clients/[id]/purchases/page.tsx",
    "lib/imports/mappers.ts",
  ], (
    "the create paths that pin the rate to zero have moved. If one legitimately " +
    "stopped sending the key, delete its entry here; if the scan stopped seeing " +
    `it, the filter above is broken and the real test is now vacuous:\n  ${zeros.join("\n  ")}`
  ));
});

test("the write type does not offer the field at all", () => {
  const api = fs.readFileSync(path.join(WEB, "lib/api/index.ts"), "utf8");
  const start = api.indexOf("export type VendorWrite = {");
  assert.ok(start > 0, "VendorWrite moved — this guard needs repointing");
  const block = api.slice(start, api.indexOf("};", start));
  assert.ok(!/tds_rate_bps/.test(block), (
    "VendorWrite declares tds_rate_bps again. Keeping it off the type is what " +
    "makes the compiler refuse the next screen; this file can only catch the " +
    "PostgREST path."
  ));
  // The READ type keeps it: the column exists, the list may show what is
  // stored, and a guard that forbade the name outright would forbid that too.
  assert.ok(/export type Vendor = \{[\s\S]*?tds_rate_bps/.test(api), (
    "`Vendor` no longer carries tds_rate_bps. The column still exists and is " +
    "readable; only writing it from a screen is the defect."
  ));
});

test("the supplier master offers no section the engine cannot price", () => {
  // An "Other (manual rate)" option sent `tds_applicable: true` with
  // `tds_section: null`, and resolve_resident_tds opens by raising 422 on
  // exactly that — so every bill from such a vendor was refused, while the
  // calculator beside the picker showed the manual rate's arithmetic and
  // taught the CA it worked.
  const page = code(fs.readFileSync(path.join(WEB, "app/accounting/suppliers/page.tsx"), "utf8"));
  assert.ok(!/["']other["']/.test(page), (
    "the supplier master offers a section outside the registry again. Every " +
    "deduction is under a section; `tds_applicable` with no section is a 422 " +
    "on every bill from that vendor."
  ));
});
