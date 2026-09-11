/**
 * NO SCREEN IN THIS PRODUCT TAKES A GOVERNMENT PORTAL'S SECRET.
 *
 * Not a password, not an OTP, not an EVC, not a DSC PIN — and not behind an
 * embedded frame of the portal either, which is the same thing wearing a
 * different hat: whatever a viewer types into a frame we rendered, they typed
 * into a page we served.
 *
 * WHY THIS IS A TEST AND NOT A CODE REVIEW NOTE
 *
 * Every one of these is a reasonable-sounding feature request. "Just let me
 * paste the OTP so it files in one click" is what a CA coming from a
 * screen-scraping product asks for on day one, and the answer has to be the
 * same on day one and on day four hundred. Prose in a file header does not
 * survive a hurried afternoon; this does. The backend states the same rule
 * over its own half, in
 * apps/api/tests/test_the_handoff_says_what_goes_in_which_box.py.
 *
 * It is also the rule the whole filing position rests on. There is no EPFO,
 * ESIC, MCA or state professional-tax API a CA firm can hold — see
 * docs/compliance/08-government-api-access-the-verified-position.md — so a
 * product that appeared to file for you could only be doing it by logging in
 * as you. That breaches the portals' own terms, and it is exactly what RBI
 * moved bank data onto the Account Aggregator framework to end.
 *
 * THE ONE THING THAT IS NOT THIS. Our OWN sign-in is a credential field, and
 * it is meant to be: PracticeSync authenticates its own users. The allowlist
 * below is those screens and nothing else, each with the reason. A file added
 * to it is a claim somebody made on purpose.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(import.meta.dirname, "..");

/** Screens that take a PRACTICESYNC secret, which is not a portal's. */
const OWN_CREDENTIALS: Record<string, string> = {
  "app/login/page.tsx":
    "the firm's own sign-in — a PracticeSync password, not a portal's",
  "app/portal/login/page.tsx":
    "the client/employee portal's own sign-in, same reason",
  "app/onboarding/page.tsx":
    "sign-up: sets a PracticeSync password and takes the e-mail verification "
    + "code Supabase sends. Our own second factor, not a government portal's",
  "app/auth/reset-password/page.tsx":
    "sets a new PracticeSync password after a reset link",
  "app/portal/activate/page.tsx":
    "a client activating their portal login sets their own password here",
  "app/portal/employee/activate/page.tsx":
    "an employee activating their portal login, same reason",
  "app/accounting/lock-year/page.tsx":
    "the firm's OWN PIN, which authorises locking a financial year. It "
    + "authenticates a partner to PracticeSync — no government portal has "
    + "ever seen it",
};

/** Matches of the WORD that are not credentials at all. Kept separate from the
 *  allowlist above on purpose: calling a bookmark toggle an "own credential"
 *  would make the list a place things go to be forgotten. */
const NOT_A_CREDENTIAL: Record<string, string> = {
  "components/knowledge/ClientInstructions.tsx":
    'title="Pin/unpin" — pinning a note to the top of a list. The word, not '
    + "the thing",
};

const GOVERNMENT_HOSTS = [
  "epfindia.gov.in", "esic.gov.in", "gst.gov.in", "incometax.gov.in",
  "mca.gov.in", "tdscpc.gov.in", "eportal.incometax.gov.in",
];

function sources(): { path: string; text: string }[] {
  const out: { path: string; text: string }[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(join(ROOT, dir))) {
      const rel = `${dir}/${entry}`;
      if (statSync(join(ROOT, rel)).isDirectory()) { walk(rel); continue; }
      if (!/\.(ts|tsx)$/.test(entry) || entry.includes(".test.")) continue;
      out.push({ path: rel, text: readFileSync(join(ROOT, rel), "utf8") });
    }
  };
  ["app", "components", "lib"].forEach(walk);
  return out;
}

/** Strip block comments and JSX comment expressions, so a file that EXPLAINS
 *  why it has no OTP field is not read as having one. The rule is about
 *  inputs; the explanations are the point of keeping them. */
function code(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
}

test("no screen but our own sign-in has a password field", () => {
  const offenders = sources()
    .filter(({ path }) => !(path in OWN_CREDENTIALS))
    .filter(({ text }) => /type\s*=\s*["']password["']/.test(code(text)))
    .map(({ path }) => path);
  assert.deepEqual(offenders, [],
    "a password box in this product is a credential-capture surface whatever "
    + "it is labelled. If this is our own authentication, add it to "
    + "OWN_SIGN_IN with the reason.");
});

test("no screen but our own sign-in asks for a one-time code", () => {
  // Placeholders and labels, which is where a field announces itself to the
  // person filling it in. `otp` alone is too loose — it appears inside
  // identifiers and prose — so this looks at what a CA would actually READ.
  const asksForACode =
    /(placeholder|aria-label|title)\s*=\s*["'][^"']*\b(otp|one[- ]time|passcode|pin|captcha|password|verification code)\b[^"']*["']/i;
  const offenders = sources()
    .filter(({ path }) => !(path in OWN_CREDENTIALS)
                       && !(path in NOT_A_CREDENTIAL))
    .filter(({ text }) => asksForACode.test(code(text)))
    .map(({ path }) => path);
  assert.deepEqual(offenders, [],
    "an OTP or EVC is typed on the portal, never in the software that prepared "
    + "the return. The filing demo's OTP stage has no input for exactly this "
    + "reason — see components/FilingDemoWizard.tsx.");
});

test("no page embeds a government portal in a frame", () => {
  const offenders: string[] = [];
  for (const { path, text } of sources()) {
    const src = code(text);
    if (!/<iframe/.test(src)) continue;
    for (const host of GOVERNMENT_HOSTS) {
      if (src.includes(host)) offenders.push(`${path} (${host})`);
    }
  }
  assert.deepEqual(offenders, [],
    "whatever a viewer types into a frame we rendered, they typed into a page "
    + "we served. Link out to the portal instead.");
});

test("the handoff screen says so, where a CA will read it", () => {
  // The refusal is worth nothing if the person it protects never learns of it:
  // a CA arriving from a product that DID log in for them will go looking for
  // the password box and conclude the feature is missing.
  const screen = readFileSync(
    join(ROOT, "components/payroll/StatutoryHandoff.tsx"), "utf8");
  assert.match(screen, /never ask you for a portal password or an OTP/,
    "the handoff must tell the CA it will never ask, not merely not ask");
});

test("both allowlists explain every entry, and every entry is real", () => {
  // An allowlist that outlives the file it excuses is how a guard rots: the
  // entry keeps passing while checking nothing, and nobody knows it is stale.
  for (const list of [OWN_CREDENTIALS, NOT_A_CREDENTIAL]) {
    for (const [path, reason] of Object.entries(list)) {
      assert.ok(reason.trim().length > 20, `${path} has no real reason`);
      assert.doesNotThrow(() => statSync(join(ROOT, path)),
        `${path} is allowlisted and does not exist — delete the entry`);
    }
  }
});
