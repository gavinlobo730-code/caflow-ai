// The browser never computes a TDS figure. CLAUDE.md: zero business logic in
// the frontend — made testable for TDS specifically, because this is where it
// was broken.
//
// Run with:
//   node --experimental-strip-types --test scripts/tds-is-computed-by-the-engine-not-the-browser.test.ts
//
// WHY THIS EXISTS
//     app/tds/page.tsx carried its own section/rate table and its own
//     arithmetic, and inserted the result straight into tds_deductions over
//     PostgREST. rbac() never ran and domain/tds was never consulted. The table
//     was wrong in eight ways at once — §194C flat at the company rate when an
//     individual/HUF is 1%, §194D at 5% where the statute says 2% individual
//     and 10% company, §194H stale since the Finance (No. 2) Act 2024, §194Q
//     charged on the whole sum where §194Q(1) charges on the excess over ₹50
//     lakh, §194IA offered when the engine does not hold it, §192 leaving the
//     previous rate in the box, no threshold anywhere, and no FY aggregate.
//
//     Rates change every Finance Act. A copy in the browser is a copy that goes
//     stale silently, and the CA sees a confident wrong number.
//
// WHAT THIS DOES NOT DO
//     It reads source, not behaviour. That the ENGINE is right is the Python
//     suite's job (tests/test_a_typed_deduction_goes_through_the_engine.py).
//     What this pins is that the browser asks it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    // .test.ts files assert about the code; they are not the code, and a test
    // that pins an allowlisted helper's behaviour must not itself be reported.
    else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)
             && !p.includes(`${path.sep}scripts${path.sep}`)) out.push(p);
  }
  return out;
}

function code(file: string): string {
  return fs.readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

// Files still allowed to hold a TDS rate, each with the reason. May only shrink.
const RATE_HOLDERS: Record<string, string> = {
  "lib/services/currencyPreview.ts":
    "estimateForeignTds — the purchase-bill editor's preview (TDS-14), not yet " +
    "fixed. It applies vendors.tds_rate_bps with no threshold, no §206AA and no " +
    "§195 surcharge, and the finding is the next part of this phase.",
  "components/purchases/PurchaseBillEditor.tsx":
    "Calls estimateForeignTds. Same finding (TDS-14); removing the call and the " +
    "helper together is that fix, not this one.",
  "app/accounting/suppliers/page.tsx":
    "One manual-rate line, reachable ONLY when tds_section === \"other\" — a " +
    "section the engine declines to answer for, so it cannot contradict the " +
    "engine the way a hardcoded table does. Display-only: the figure is rendered " +
    "and never saved. It is labelled \"manual rate\" on screen. Revisit with " +
    "Phase 4's unknown-section work (§194IA and friends).",
  "lib/services/payrollTdsEstimate.ts":
    "§192 SALARY TDS, not Chapter XVII-B — a different engine " +
    "(routers/payroll.py::_compute_tds_192) and a different finding. The " +
    "module's own docstring already declares itself a standing CLAUDE.md " +
    "violation tracked as roadmap R2.10 (move payroll compute server-side), " +
    "and says any FY rate change must update both it and statutory_rates.py. " +
    "Absorbing it into this phase would hide an item that is already named.",
};

test("no screen carries its own table of TDS rates", () => {
  // A rate table is a map from a section number to a percentage. Spelling it as
  // a RULE rather than as one variable name, because the last guard that named
  // a spelling missed four tables.
  const offenders: string[] = [];
  for (const file of walk(WEB)) {
    const rel = path.relative(WEB, file);
    if (rel in RATE_HOLDERS) continue;
    const src = code(file);
    // "194J": { ... 10 ... }  /  "194J": 10  /  194J: 10
    const table = /["']?19[3-6][A-Z]{0,2}["']?\s*:\s*(\{[^}]*\b\d+(\.\d+)?\b[^}]*\}|\d+(\.\d+)?)/g;
    const hits = [...src.matchAll(table)]
      // A label-only map is fine and is what the screens keep.
      .filter((m) => !/^\s*["'][^"']*["']\s*$/.test(m[1]));
    if (hits.length >= 3) offenders.push(`${rel} (${hits.length} sections with numbers)`);
  }
  assert.deepEqual(
    offenders, [],
    "a TDS rate table has reappeared in the browser. Rates change every Finance " +
    "Act; the only copy lives in apps/api/domain/tds/section_rates.py and " +
    "reaches a screen through GET /api/tds/sections.",
  );
});

test("no screen multiplies an amount by a TDS rate", () => {
  const offenders: string[] = [];
  for (const file of walk(WEB)) {
    const rel = path.relative(WEB, file);
    if (rel in RATE_HOLDERS) continue;
    const src = code(file);
    // Arithmetic that APPLIES A RATE, not arithmetic that formats money.
    // `tdsDeductedPaise / 100` is paise to rupees for a CSV column and
    // `rate_bps / 100` is basis points to a percentage — neither computes a
    // withholding, and a guard that flags them gets switched off. So the
    // divisor 100 and 10000 are excluded, and the multiplication has to name a
    // RATE on one side.
    for (const re of [
      /\w*[Tt]ds\w*\s*=\s*Math\.(round|floor|ceil)\s*\([^)]*\*/g,
      /\w+\s*\*\s*\w*[Rr]ate\w*\s*\/\s*(100|10000)\b/g,
      /\w*[Rr]ate\w*\s*\*\s*\w*([Pp]aise|[Aa]mount|[Gg]ross|[Tt]axable)\w*/g,
    ]) {
      if (re.test(src)) { offenders.push(`${rel}  (${re})`); break; }
    }
  }
  assert.deepEqual(
    offenders, [],
    "TDS is being computed in the browser. The rate depends on the section, on " +
    "whether the payee is a company (the PAN's 4th character), on whether a PAN " +
    "is on file at all (§206AA floors it at 20%), on the section's threshold and " +
    "on the year's running aggregate with its §200 credit — none of which the " +
    "browser has. Post to /api/tds-workspace/deductions and let the engine answer.",
  );
});

test("the /tds screen records a deduction through the API", () => {
  const src = code(path.join(WEB, "app/tds/page.tsx"));
  assert.match(src, /createTdsDeduction\(/, "the save must go through the API");
  assert.match(src, /previewTdsDeduction\(/, "the live figure must come from the server");
  assert.match(src, /listTdsSections\(/, "the section list must come from the engine");
  // ...and no longer writes the register itself.
  assert.doesNotMatch(
    src, /\.from\(\s*["']tds_deductions["']\s*\)[\s\S]{0,600}?\.insert\(/,
    "the screen still inserts into tds_deductions over PostgREST",
  );
});

test("the preview and the save are the same server function", () => {
  // A preview computed by a DIFFERENT route than the write is exactly the
  // defect TDS-14 describes on the purchase-bill side: the editor shows a
  // browser-side rate × base, the server then applies a threshold, a §206AA
  // floor and an FY aggregate, and the figure the CA approved is not the figure
  // that lands.
  const src = code(path.join(WEB, "lib/data/tds.ts"));
  assert.match(src, /\/api\/tds-workspace\/deductions\/preview/);
  assert.match(src, /\/api\/tds-workspace\/deductions["'`]/);
  // computeTdsAmount is NOT the preview: it has no place for the year's
  // aggregate, so it answers as though every payment were the first.
  const preview = src.slice(src.indexOf("export async function previewTdsDeduction"));
  assert.doesNotMatch(preview.slice(0, 1200), /compute-amount/);
});

test("the CSV import does not take a rate from the spreadsheet", () => {
  const src = code(path.join(WEB, "app/tds/page.tsx"));
  assert.doesNotMatch(
    src, /parseFloat\(\s*row\.tds_rate/,
    "whatever a CA typed into a spreadsheet column became the withholding, " +
    "unchecked against the section on the same row",
  );
});

test("every allowlisted rate holder gives its reason", () => {
  for (const [file, why] of Object.entries(RATE_HOLDERS)) {
    assert.ok(fs.existsSync(path.join(WEB, file)),
      `${file} is allowlisted but does not exist — delete the entry`);
    assert.ok(why.length > 40, `${file}: say which finding covers it`);
  }
});
