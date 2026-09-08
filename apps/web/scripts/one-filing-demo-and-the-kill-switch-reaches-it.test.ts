// There is ONE filing demo, and ENABLE_FILING_SIMULATION reaches it. Run with:
//   node --experimental-strip-types --test scripts/one-filing-demo-and-the-kill-switch-reaches-it.test.ts
//
// WHY THIS EXISTS
//     Until 2026-09-05 there were TWO demo-filing implementations, and the one
//     CLAUDE.md did not know about was the unsafe one.
//
//     components/DemoFilingModal, reachable from /deadlines, generated the demo
//     reference and ran the validation IN THE BROWSER (lib/filing/demoFiling),
//     then wrote the result straight to demo_filings over PostgREST. It never
//     called the server. So it never asked /api/filing-demo/capabilities, and
//     ENABLE_FILING_SIMULATION — which CLAUDE.md calls the KILL SWITCH, to be
//     set false on any deployment that records real filings — did not reach it.
//     Turning the flag off left that button simulating filings and persisting
//     references.
//
//     The shared framework does it properly: services/filing_demo/ builds the
//     stages, the flag gates the capabilities probe AND every preview endpoint,
//     and components/FilingDemoWizard renders whatever the server returns with
//     a banner and SPECIMEN badge it has no code path to omit.
//
//     Both are deleted. These assertions are INVERTED — their subject is code
//     that must never exist again — because "just add a Simulate button here
//     too, it's only a modal" is a change nobody would flag in review, and the
//     thing it would quietly cost is the kill switch.
//
// AND ONE MORE THING THAT MUST NEVER COME BACK: A CREDENTIAL FIELD
//     The wizard's OTP stage used to render a six-digit input and accept any
//     value. The STEP is real and stays — nearly every Indian return is signed
//     with an EVC or Aadhaar OTP — but the input is gone, along with the state
//     behind it. CLAUDE.md, on real filing: "an EVC OTP field in this app is a
//     credential capture surface whatever it is labelled." A demo that trains a
//     CA to type a portal OTP into their practice software is how that habit
//     arrives before the real thing does.
//
//     It is also the more faithful rendering, which is why removing it cost the
//     walk-through nothing: the code is typed on gst.gov.in or incometax.gov.in,
//     never in the software that prepared the return, so a field here taught the
//     step in the wrong PLACE.
//
//     The same inverted shape is used, for the same reason: "let them type
//     something, it's only a demo" is a change nobody would flag in review.
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
    else if (/\.(ts|tsx)$/.test(e.name) && !p.includes(`${path.sep}scripts${path.sep}`)) out.push(p);
  }
  return out;
}

const SOURCES = walk(WEB);

function read(p: string) {
  return fs.readFileSync(p, "utf8");
}

test("the deleted browser-side demo modules are gone and stay gone", () => {
  for (const gone of [
    "components/DemoFilingModal.tsx",
    "components/DemoModeBanner.tsx",
    "lib/filing/demoFiling.ts",
    "lib/data/demoFilings.ts",
  ]) {
    assert.equal(
      fs.existsSync(path.join(WEB, gone)), false,
      `${gone} is back. It was the second filing-demo implementation and the ` +
      `one the kill switch could not reach — see the header of this file.`,
    );
  }
});

test("no screen generates a filing reference in the browser", () => {
  // The server owns the reference. Its demo flows return an honest
  // SIM-NOT-FILED value, and any realistic-looking one carries a SPECIMEN
  // badge at the point of display. A reference minted in the browser has
  // neither property and nothing to enforce them.
  const offenders = SOURCES.filter((p) =>
    /generateDemoReference|DEMO-ARN-|DEMO-SRN-|SIM-GST-/.test(read(p)));
  assert.deepEqual(
    offenders.map((p) => path.relative(WEB, p)), [],
    "a filing reference is being built in the browser",
  );
});

test("nothing writes demo_filings from the browser", () => {
  // rbac() never runs on a PostgREST call, so a write here is checked only by
  // RLS — and RLS cannot see ENABLE_FILING_SIMULATION at all.
  const offenders = SOURCES.filter((p) => {
    const src = read(p);
    return /from\(["']demo_filings["']\)/.test(src)
        && /\.(insert|upsert|update|delete)\(/.test(src);
  });
  assert.deepEqual(
    offenders.map((p) => path.relative(WEB, p)), [],
    "demo_filings is being written from the browser",
  );
});

test("every screen that offers a filing demo asks the server first", () => {
  // The dead-control rule, and the kill switch in one: a screen that renders
  // FilingDemoWizard must also probe capabilities, because only the server
  // knows whether demos are enabled and which flows this role may run.
  const users = SOURCES.filter((p) => /<FilingDemoWizard/.test(read(p)));
  assert.ok(users.length >= 5, `expected the wizard on the module screens, found ${users.length}`);
  for (const p of users) {
    assert.match(
      read(p), /fetchFilingDemoCapabilities/,
      `${path.relative(WEB, p)} renders FilingDemoWizard without probing capabilities`,
    );
  }
});

test("the wizard cannot render a result without its SPECIMEN badge and truth lines", () => {
  const src = read(path.join(WEB, "components/FilingDemoWizard.tsx"));
  assert.match(src, /SPECIMEN/, "the wizard lost its SPECIMEN badge");
  assert.match(src, /DEMO — nothing is being filed/, "the wizard lost its DEMO banner");
});

test("the guard would actually catch a reference minted in the browser", () => {
  // The negative control. Without it a broken walk() — a wrong root, a filter
  // that excludes everything — would make all of the above pass for ever.
  assert.ok(SOURCES.length > 50, `walk() found only ${SOURCES.length} sources`);
  const sample = "const ref = 'DEMO-ARN-' + suffix;";
  assert.match(sample, /DEMO-ARN-/, "the pattern itself no longer matches");
});

test("the wizard takes no credential — no OTP field, no password field", () => {
  // CLAUDE.md, on real filing: "an EVC OTP field in this app is a credential
  // capture surface whatever it is labelled". The demo used to render one and
  // accept any six digits. The STEP stays — it is real, and every GST and
  // income-tax filing is signed that way — but the input is gone, and so is
  // the state behind it, because a component still holding a six-digit value
  // is one edit away from rendering a box for it again.
  //
  // It is also the more faithful rendering. The OTP is typed on gst.gov.in or
  // incometax.gov.in, never in the software that prepared the return, so a
  // field here taught the step in the wrong place.
  const src = read(path.join(WEB, "components/FilingDemoWizard.tsx"));
  assert.doesNotMatch(
    src, /<input[^>]*\b(?:aria-label|placeholder)="[^"]*(?:OTP|otp|PIN|password)/,
    "the wizard has an OTP or credential input again",
  );
  assert.doesNotMatch(src, /type="password"/, "the wizard has a password field");
  assert.doesNotMatch(
    src, /setOtp|verifyOtp/,
    "the wizard is holding OTP state again — the input follows the state",
  );
  assert.match(
    src, /stage\?\.kind === "otp"/,
    "the otp STAGE must still render; it is the step that is real",
  );
});

test("no screen anywhere collects a portal credential for a demo", () => {
  // Wider than the wizard: the point of deleting the field is that nobody
  // rebuilds it beside the wizard, the way the browser-side demo was built
  // beside the server one.
  const offenders = SOURCES.filter((p) => {
    const src = read(p);
    return /\b(?:demo|filing|evc|otp)/i.test(src)
        && /<input[^>]*type="password"/.test(src);
  });
  assert.deepEqual(
    offenders.map((p) => path.relative(WEB, p)), [],
    "a filing screen is collecting a credential",
  );
});

test("the transmit stage says nothing is being sent, in its own frame", () => {
  // The stage that most looks like a real upload — ticks appearing one by one
  // — and the one most likely to be screenshotted mid-play. The sticky banner
  // says it too; this says it inside the frame the ticks are in, and it is
  // rendered unconditionally rather than supplied by a flow.
  const src = read(path.join(WEB, "components/FilingDemoWizard.tsx"));
  assert.match(src, /Nothing is being sent/);
});

test("the success panel cannot show its heading without disowning it", () => {
  // "✓ Filing successful" is what makes the walk-through recognisable and it
  // is the single most dangerous string in the product. It keeps its DEMO
  // badge and now carries a line saying whose words they are — rendered by
  // the component, so no server-side flow can leave it out.
  const src = read(path.join(WEB, "components/FilingDemoWizard.tsx"));
  assert.match(src, /Filing successful/);
  assert.match(src, /That is what the portal would say/);
  assert.match(src, /nothing was sent, and no return has been filed/);
});

test("the wizard shows what changes when the filing is real", () => {
  // Required of every flow server-side (services/filing_demo/common.envelope
  // will not build without it), so there is no empty state: the panel names
  // the registration that gates real filing and what the CA will do
  // differently. It is what makes the demo a sales asset rather than a toy.
  const src = read(path.join(WEB, "components/FilingDemoWizard.tsx"));
  assert.match(src, /when_this_is_real/);
  assert.match(src, /What changes when this is real/);
});

test("the credential guard would catch a field that came back", () => {
  // The negative control for the two credential tests above: assertions that
  // something is ABSENT prove nothing until the pattern is shown matching.
  const otpField = '<input value={otp} aria-label="OTP" className="..." />';
  assert.match(otpField, /<input[^>]*\baria-label="[^"]*OTP/);
  const passwordField = '<input type="password" name="evc" />';
  assert.match(passwordField, /<input[^>]*type="password"/);
});
