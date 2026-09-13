// CGST Rule 43 reaches the screen — the classification, and the working.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-capital-good-says-what-it-is-used-for.test.ts
//
// FA-19. A client making both taxable and exempt supplies must reverse
// one-sixtieth of the credit on each COMMON capital good every month for five
// years, apportioned by exempt turnover (Rule 43(1)(c)–(h)). The product
// computed nothing and prompted nothing, so either the CA kept a spreadsheet
// or the client under-reversed — an interest-bearing default under §50.
//
// The arithmetic is apps/api/domain/gst/rule_43.py and is tested there. What
// these pin is the half a backend test cannot see:
//
//   * the asset form ASKS which of the three uses applies, and sends it;
//   * it does not ask where there is nothing to apportion;
//   * the GSTR-3B screen RENDERS the working, including the assets left out
//     of it — a figure understated by an unclassified asset reads exactly like
//     a correct one.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");
/** Source with comments stripped — what actually runs and renders. */
const code = (src: string) =>
  src.replace(/\{\/\*[\s\S]*?\*\/\}/g, " ")
     .replace(/\/\*[\s\S]*?\*\//g, " ")
     .replace(/^\s*\/\/.*$/gm, " ");

const ASSETS = code(read("app/clients/[id]/fixed-assets/page.tsx"));
const GSTR3B = code(read("app/gst/gstr3b/page.tsx"));
const DATA = code(read("lib/data/gst.ts"));

// The Rule 43 panel binds its working to `r43`, not `w`, and that is not a
// style choice: apps/api/tests/test_gstr3b_screen_contract.py extracts every
// `w.a.b` on this screen and walks it against a real from-books response, so a
// second object called `w` makes that contract test fail on fields the
// from-books endpoint has no reason to return.

// ── the classification ───────────────────────────────────────────────────────

test("the asset form offers all three Rule 43 uses", () => {
  for (const v of ["exclusively_taxable", "common", "exclusively_exempt"]) {
    assert.match(ASSETS, new RegExp(`<option value="${v}">`),
      `the form does not offer ${v}`);
  }
  // …and the unanswered state, which is the default and is not a fourth use.
  assert.match(ASSETS, /<option value="">Not decided yet<\/option>/);
});

test("nothing is pre-selected", () => {
  // A default would classify every asset the moment it is created, which is
  // exactly the guess the column exists to avoid: assuming common reverses
  // credit §16(1) gives, assuming taxable leaves a shortfall 43(1)(h) charges
  // interest on.
  assert.match(ASSETS, /rule_43_use:\s*"" as ""/);
});

test("what the CA picks is actually sent", () => {
  // The whole classification is worthless if the payload drops it — the
  // working then reports every asset as unclassified, which reads like a data
  // problem rather than a dropped field.
  assert.match(ASSETS, /rule_43_use:\s+form\.rule_43_use \|\| undefined,/);
  assert.match(ASSETS, /onChange=\{e => setForm\(f => \(\{ \.\.\.f, rule_43_use: e\.target\.value as typeof f\.rule_43_use \}\)\)\}/);
});

test("an empty answer is omitted rather than sent as an empty string", () => {
  // "" is not one of the three the model accepts and not what the CHECK
  // constraint allows; omitting leaves the column NULL, which is what "not
  // classified" means everywhere else the asset is read.
  assert.doesNotMatch(ASSETS, /rule_43_use:\s+form\.rule_43_use,/);
});

test("it is asked only where credit was actually claimed", () => {
  // There is nothing to apportion on tax §17(5) already blocked (it was
  // capitalised and depreciates) or on an asset carrying no tax at all.
  assert.match(ASSETS, /\{form\.itc_eligible === "yes" && \(\s*<Field label="What it is used for\?|\{form\.itc_eligible === "yes" && \(/);
  const at = ASSETS.indexOf("What is it used for? (CGST Rule 43)");
  assert.ok(at > 0, "the control is not on the form");
  const before = ASSETS.slice(Math.max(0, at - 400), at);
  assert.match(before, /form\.itc_eligible === "yes"/,
    "the control must be gated on the credit having been claimed");
});

test("the screen says what each choice means", () => {
  assert.match(ASSETS, /One-sixtieth of this credit is apportioned by exempt turnover/);
  assert.match(ASSETS, /No credit was available on this asset/);
  assert.match(ASSETS, /the whole credit stands/i);
  // And why leaving it blank is a real option rather than an oversight.
  assert.match(ASSETS, /assuming it is common reverses credit/);
});

// ── the working ──────────────────────────────────────────────────────────────

test("the GSTR-3B screen fetches the Rule 43 working", () => {
  assert.match(GSTR3B, /fetchRule43Working\(clientId, period\)/);
  assert.match(DATA, /\/api\/gst-workspace\/itc\/rule-43\?client_id=/);
});

test("a failure to work Rule 43 does not fail the return", () => {
  // Same shape as Rule 37 beside it: the return's own figures stand on their
  // own, and a swallowed failure would be worse than a stated one.
  assert.match(GSTR3B, /setRule43Error\(e instanceof Error \? e\.message : "Could not check Rule 43"\)/);
  assert.match(GSTR3B, /Rule 43 not checked\./);
});

test("the working is cleared when the client or the period changes", () => {
  // A working for April rendered beside May's return is a wrong figure with a
  // right-looking heading.
  assert.equal((GSTR3B.match(/setRule43\(null\)/g) ?? []).length, 3);
});

test("Te is rendered per head, not as one total", () => {
  // Rule 43(2) computes it separately for IGST, CGST and SGST/UTGST, and one
  // total cannot be allocated across the three output heads.
  assert.match(GSTR3B, /\(\["igst", "cgst", "sgst"\] as const\)\.map/);
});

test("the assets left OUT of the working are rendered", () => {
  // THE POINT OF THE PANEL. An unclassified asset contributes nothing, so the
  // Te above is understated by whatever it carries — and no number on the
  // screen can say so.
  assert.match(GSTR3B, /r43\.gaps\.map/);
  assert.match(GSTR3B, /not in this\s+working, and should be/);
  assert.match(GSTR3B, /Record the use on the asset in the client&apos;s Fixed Assets tab/);
});

test("a refusal is shown as a refusal, not as a nil reversal", () => {
  // Rule 43(1)(g)'s proviso sends the CA to the last period whose turnover is
  // known. Rendering that as "no reversal due" would be a wrong answer with a
  // reassuring shape.
  assert.match(GSTR3B, /if \(r43\.refused\)/);
  assert.match(GSTR3B, /Rule 43 could not be worked for this period/);
});

test("nil-because-no-exempt-supplies and nil-because-nothing-running are different sentences", () => {
  assert.match(GSTR3B, /No common capital good is inside its five-year life this period/);
  assert.match(GSTR3B, /no exempt supplies this period/);
});

test("the caveats travel with the figures", () => {
  // The (a)→(c) transition and the Explanation's excise exclusion are not
  // modelled, and a working shown without those sentences is a disclosure a
  // reader would rely on.
  assert.match(GSTR3B, /r43\.caveats\.map/);
});

test("the panel says the figure is not in Table 4(B) yet, and how to get it there", () => {
  // Same honesty as Rule 37: nothing is posted, so folding it into 4(B) would
  // put the return out of step with the ledger.
  const at = GSTR3B.indexOf("Rule 43 — capital goods used partly for exempt supplies");
  assert.ok(at > 0);
  assert.match(GSTR3B.slice(at), /Not included in Table 4\(B\) above\./);
  assert.match(GSTR3B.slice(at), /\{r43\.how_to_declare\}/);
});

test("a client with no fixed assets gets no panel at all", () => {
  // An empty Rule 43 box on every service client's return is noise, and noise
  // is what makes a real one get skipped.
  assert.match(GSTR3B, /if \(r43\.assets\.length === 0\) \{\s*return null;/);
});
