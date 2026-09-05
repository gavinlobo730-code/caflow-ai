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
