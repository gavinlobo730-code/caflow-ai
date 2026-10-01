// The employee drawer (payroll roster) gets a master-data Profile section, no
// longer defaults to the leaver's Full & Final screen on every open, and
// closes on Escape like every other full-screen overlay in the product
// (apex-payroll-yearend-07).
//
// Run with:
//   node --experimental-strip-types --test \
//     scripts/employee-drawer-has-a-profile-section-and-closes-on-escape.test.ts
//
// WHAT WAS WRONG
//     SECTIONS had no PAN/UAN/ESI/bank-account/joining-date/basic/HRA/DA
//     editor, although PATCH /employees/{id} (EmployeeUpdateIn) already
//     accepted every one of those fields — only the UI to reach it from this
//     drawer was missing. `useState<Section>("settlement")` opened every
//     employee, active or not, on the leaver's screen. And there was no
//     `keydown` listener at all, so the only way out of the full-screen
//     overlay was the explicit Close button.
//
// THE FIX
//     A "profile" section, first in SECTIONS and the new default, saving
//     through the SAME api.payroll.updateEmployee(...) door
//     AddEmployeeModal.tsx already uses — sending only fields
//     EmployeeUpdateIn actually accepts. A document-level keydown listener,
//     the same shape components/ui/drawer.tsx and ClientFormModal.tsx use.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const FILE = "components/payroll/EmployeeDrawer.tsx";

function read(): string {
  return fs.readFileSync(path.join(WEB, FILE), "utf8");
}

function stripped(): string {
  return stripComments(read());
}

test("there is a profile section, first in SECTIONS", () => {
  const src = stripped();
  const m = /const SECTIONS: \{[^}]*\}\[\] = \[([\s\S]*?)\n\];/.exec(src);
  assert.ok(m, "SECTIONS array not found");
  const firstEntry = m[1].trim();
  assert.match(firstEntry, /^\{ key: "profile"/,
    "profile must be the FIRST entry, since it is also the new default section");
});

test("the drawer defaults to profile, not settlement", () => {
  const src = stripped();
  assert.match(src, /const \[section, setSection\] = useState<Section>\("profile"\)/);
  assert.doesNotMatch(src, /useState<Section>\("settlement"\)/,
    "every employee, active or not, must not open on the leaver's F&F screen");
});

test("ProfileSection renders PAN, UAN, ESI number, bank account, IFSC, joining date, basic, HRA and DA", () => {
  const m = /function ProfileSection\([\s\S]*?\n\}\n/.exec(stripped());
  assert.ok(m, "ProfileSection not found");
  const body = m[0];
  for (const label of ["PAN", "UAN", "ESI number", "Joining date",
                       "Bank account number", "Bank IFSC", "HRA %", "DA %"]) {
    assert.match(body, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
      `ProfileSection must show a "${label}" field`);
  }
  assert.match(body, /<Money label="Basic"/);
});

test("ProfileSection saves through the same door AddEmployeeModal uses, with only EmployeeUpdateIn's own fields", () => {
  const src = stripped();
  const m = /function ProfileSection\([\s\S]*?\n\}\n/.exec(src);
  assert.ok(m);
  const body = m[0];
  assert.match(body, /api\.payroll\.updateEmployee\(employee\.id, \{/);
  // Every key sent must be a real EmployeeUpdateIn field (apps/api/models/payroll.py) —
  // no field invented here that the backend model does not accept.
  const ALLOWED = new Set([
    "pan", "uan", "esi_number", "bank_account_no", "bank_ifsc",
    "joining_date", "basic_paise", "hra_percent", "da_percent",
  ]);
  const callMatch = /api\.payroll\.updateEmployee\(employee\.id, \{([\s\S]*?)\n\s*\}\);/.exec(body);
  assert.ok(callMatch, "could not isolate the updateEmployee(...) payload");
  const keys = [...callMatch[1].matchAll(/^\s*(\w+):/gm)].map((mm) => mm[1]);
  assert.ok(keys.length >= 8, `expected at least 8 fields sent, found ${keys.length}`);
  for (const k of keys) {
    assert.ok(ALLOWED.has(k), `${k} is not a field this fix was asked to send`);
  }
});

test("typed junk in a percent or amount field refuses rather than saving as unchanged", () => {
  const m = /function ProfileSection\([\s\S]*?\n\}\n/.exec(stripped());
  assert.ok(m, "ProfileSection not found");
  const body = m[0];
  assert.match(body, /bpsFromPercentInput\(hraPercent\)/);
  assert.match(body, /bpsFromPercentInput\(daPercent\)/);
  assert.match(body, /paiseFromRupeeInput\(basic\)/);
  assert.match(body, /throw new Error/);
});

test("the drawer closes on Escape via a document keydown listener", () => {
  const src = stripped();
  assert.match(src, /addEventListener\("keydown"/);
  assert.match(src, /e\.key === "Escape"/);
  assert.match(src, /onClose\(\)/);
  assert.match(src, /removeEventListener\("keydown"/,
    "the listener must be cleaned up in the effect's return");
});
