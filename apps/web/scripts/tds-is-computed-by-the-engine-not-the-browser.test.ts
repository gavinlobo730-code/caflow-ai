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
  "app/accounting/suppliers/page.tsx":
    "One manual-rate line, reachable ONLY when tds_section === \"other\" — a " +
    "section the engine declines to answer for, so it cannot contradict the " +
    "engine the way a hardcoded table does. Display-only: the figure is rendered " +
    "and never saved. It is labelled \"manual rate\" on screen. Revisit with " +
    "Phase 4's unknown-section work (§194IA and friends).",
};

// The allowlist SHRANK, and this is the record of it. `payrollTdsEstimate.ts`
// held §192's slab ladder, §87A rebate and §2(29C) brackets, hard-coded to FY
// 2025-26 and deliberately not FY-versioned; its own docstring called itself a
// standing CLAUDE.md violation, tracked as roadmap R2.10. PAY-10 closed it:
// GET /api/payroll/tds-projection answers off `_compute_slip`, the same
// function the payroll run pays from.
test("the §192 browser estimator is gone, and stays gone", () => {
  assert.equal(fs.existsSync(path.join(WEB, "lib/services/payrollTdsEstimate.ts")), false,
    "lib/services/payrollTdsEstimate.ts is back — §192 is computed in " +
    "routers/payroll.py::_compute_slip and served by /api/payroll/tds-projection");
  assert.equal("lib/services/payrollTdsEstimate.ts" in RATE_HOLDERS, false,
    "the allowlist may only shrink");
});

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

test("a TDS period is a financial year AND a quarter, never one of them", () => {
  // TDS-03's structural half. tds_deductions.quarter carried the compound
  // "Q3 2025-26" while tds_returns, tds_challans and tds_certificates all hold
  // the year in financial_year and CHECK quarter IN ('Q1'..'Q4'). Migration 347
  // normalises the register onto the schema's own vocabulary; these are the
  // reads that have to speak it.
  //
  // RE-POINTED, AND THE SCAN WIDENED. This used to read `lib/data/tds.ts`
  // alone and assert that both tables were still read from it. They are not:
  // `getTDSDeductions` and `getTDSChallans` existed only to feed the
  // browser-side return assembly, and both went with it — which is a STRONGER
  // outcome than the property this guarded, so the old assertion firing was
  // the guard doing its job. But four readers survive on two other screens,
  // and the original scan never saw them. It does now.
  const readers: { file: string; chain: string }[] = [];
  for (const file of walk(WEB)) {
    const src = code(file);
    for (const table of ["tds_deductions", "tds_challans"]) {
      const marker = `.from("${table}")`;
      let at = src.indexOf(marker);
      while (at !== -1) {
        // The chain as written, up to the statement's end.
        let chain = src.slice(at, at + Math.max(0, src.indexOf(";", at) - at) || undefined);
        // AND the piecewise form, which is the one that hid the bug:
        //     let q = sb.from("tds_challans")…;
        //     if (financialYear) q = q.eq("financial_year", financialYear);
        //     if (quarter)       q = q.eq("quarter", quarter);
        // The filters are in different STATEMENTS from the .from(), so a scan
        // that stopped at the first `;` would find no quarter filter and pass
        // vacuously — the same blind spot the backend's direct-write scan had
        // with its 400-character cap.
        const assigned = /(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=[^;]*$/
          .exec(src.slice(Math.max(0, at - 200), at));
        if (assigned) {
          const name = assigned[1];
          const rest = src.slice(at, at + 2000);
          for (const line of rest.split("\n")) {
            if (new RegExp(`\\b${name}\\s*=\\s*${name}\\s*\\.`).test(line)) chain += line;
          }
        }
        readers.push({ file: path.relative(WEB, file), chain });
        at = src.indexOf(marker, at + 1);
      }
    }
  }

  for (const { file, chain } of readers) {
    if (!/\.eq\("quarter"/.test(chain)) continue;
    assert.match(
      chain, /\.eq\("financial_year"/,
      `${file}: a TDS table is filtered by quarter and not by financial_year, ` +
      "so a Q3 return reconciles against every Q3 the client has ever filed",
    );
  }

  // The stronger property that replaced the old assertion: the data layer no
  // longer reads either table at all. A reader here is one import away from
  // being the return assembly again — it is what those two functions were.
  const layer = code(path.join(WEB, "lib/data/tds.ts"));
  for (const table of ["tds_deductions", "tds_challans"]) {
    assert.doesNotMatch(
      layer, new RegExp(`\\.from\\("${table}"\\)`),
      `lib/data/tds.ts reads ${table} from the browser again. The quarter's ` +
      "statement is built server-side from the posted books " +
      "(/api/tds/{26q,24q,27q}/from-books) — assembling it here is what set " +
      "every deductee's deposited amount to its deducted amount (TDS-29) and " +
      "what made an invented TAN necessary.",
    );
  }

  // And the screen must send the bare quarter, not a label. "Q1 (Apr-Jun)" was
  // a third spelling that matched nothing on either side.
  const page = code(path.join(WEB, "app/tds/returns/page.tsx"));
  assert.match(page, /QUARTERS(?::\s*TDSQuarter\[\])?\s*=\s*\["Q1",\s*"Q2",\s*"Q3",\s*"Q4"\]/,
    "the quarter sent to the API must be Q1..Q4 — the label belongs in " +
    "QUARTER_LABELS, which is what it is for");
});

test("the section dropdown offers only what the save will accept", () => {
  // §206C is TCS — collected by a SELLER from a BUYER and reported on Form
  // 27EQ. It sits in the rate registry as reference data, and
  // `GET /api/tds/sections` serves the registry, so the supplier screen
  // offered it. Nothing refused it, so a CA could mark a vendor §206C and
  // every bill from that vendor withheld 0.1% of the WHOLE amount — the
  // entry's threshold is zero, so it fires on the first rupee — with the row
  // stamped 26Q by `return_type_for`, which routes on residency and never
  // sees the section. On a bill you are PAYING there is nothing to collect at
  // all.
  //
  // The server decides eligibility (`vendor_eligible`, from the one function
  // `domain/tds/residency.deduction_section_refusal`). What is pinned here is
  // that the screen ASKS — a browser-side exclusion list is how the Schedule
  // III captions drifted in both directions at once.
  const page = code(path.join(WEB, "app/accounting/suppliers/page.tsx"));
  assert.match(page, /vendor_eligible/,
    "the supplier screen must filter its TDS section list on the server's " +
    "own vendor_eligible flag");
  assert.doesNotMatch(page, /"206C"|'206C'/,
    "a browser-side exclusion list is a second place to decide this, and it " +
    "will drift from the first");
});

test("the purchase-bill editor asks the server what this bill withholds", () => {
  // TDS-14. The editor showed `estimateForeignTds(base, vendor.tds_rate_bps)` —
  // a bare rate × base — and subtracted it as "Net payable", while the save
  // branches on RESIDENCY first and then applies a section threshold, the
  // year's aggregate and the §206AA floor, or §195 with surcharge and cess.
  // A sub-threshold §194J bill previewed tax and saved zero.
  const editor = code(path.join(WEB, "components/purchases/PurchaseBillEditor.tsx"));
  assert.match(editor, /useServerTdsPreview/,
    "the editor must get its TDS figure from the server");
  assert.doesNotMatch(editor, /estimateForeignTds/,
    "the browser-side estimate is back");

  const hook = code(path.join(WEB, "lib/purchases/serverTdsPreview.ts"));
  assert.match(hook, /\/api\/purchase-bills\/tds-preview/,
    "the preview must call the endpoint that runs the save's own code path");

  // And the helper itself is gone, not merely uncalled: a rate × base helper
  // left in the tree is one import away from being the preview again.
  const helpers = code(path.join(WEB, "lib/services/currencyPreview.ts"));
  assert.doesNotMatch(helpers, /estimateForeignTds|convertBaseToForeignMinor/,
    "delete the helper, do not just stop calling it");
});

test("the preview never shows a TDS figure it did not get from the server", () => {
  // The failure mode a preview like this invites: keep the last answer on
  // screen while the amount changes underneath it, or fall back to a local
  // estimate when the request fails. Either puts a number in front of a CA
  // that the save will not produce, which is the whole of TDS-14.
  const editor = code(path.join(WEB, "components/purchases/PurchaseBillEditor.tsx"));
  assert.match(editor, /tds\.data\?\.tds_paise \?\? null/,
    "tdsPaise must be null when there is no server answer, not 0 and not stale");
  assert.match(editor, /tds\.loading &&/,
    "the in-flight state must be rendered, or a stale figure reads as current");
  assert.match(editor, /tds\.error/,
    "a refusal is the useful answer — §195 refuses where chargeability or the " +
    "treaty position is unknown, and the save will refuse identically");
});
