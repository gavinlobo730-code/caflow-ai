// An entity is only offered what its entity type actually obliges it to file.
// Run with:
//   node --experimental-strip-types --test scripts/entity-obligations.test.ts
//
// WHY THIS EXISTS
//     A client that is a PROPRIETORSHIP was shown an "MCA Compliance
//     Workspace" — Company Master, Directors, Annual Filings, Event Filings —
//     whose first screen read "No companies registered". That reads like
//     missing data. It is not: a proprietorship has no registration with the
//     Registrar of Companies for anything to be missing FROM. Year End had the
//     same shape, advertising "Schedule III financial statements" to entities
//     Schedule III does not bind.
//
//     The fix is one predicate module, lib/entityObligations.ts, imported by
//     every call site. This file is what stops the rules drifting back into
//     the pages, and — more importantly — what stops the LLP case being
//     "simplified" into the company case.
//
// THE LAW BEING PINNED
//     AOC-4 (§137), MGT-7 (§92) and ADT-1 (§139) of the Companies Act 2013
//     bind COMPANIES. A partnership firm registers with the Registrar of
//     FIRMS under the Indian Partnership Act 1932 — a different registrar
//     entirely — and a proprietorship registers nowhere.
//
//     An LLP is the trap. It IS on the MCA portal, with a DPIN and an LLPIN,
//     so "LLP has no MCA obligation" is wrong. But it files Form 11 and
//     Form 8 under the LLP Act 2008, so "LLP is a company" is also wrong, and
//     it is the wrong answer that would silently REPLACE the bug being fixed
//     here. Both halves are asserted below.
//
//     Schedule III (Companies Act 2013 §129) prescribes the FORM of a
//     company's accounts. Everyone else still prepares a balance sheet and a
//     P&L; they just do not call it Schedule III.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  mcaRegime,
  hasMcaObligations,
  isCompaniesActCompany,
  usesScheduleIII,
  mcaScopeNote,
} from "../lib/entityObligations.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

// ── The entities with no MCA registration at all ───────────────────────────

test("a proprietorship has no MCA obligations", () => {
  assert.equal(hasMcaObligations("Proprietorship"), false);
  assert.equal(isCompaniesActCompany("Proprietorship"), false);
  assert.equal(mcaRegime("Proprietorship"), "none");
});

test("a partnership firm has no MCA obligations — it files with the Registrar of FIRMS", () => {
  assert.equal(hasMcaObligations("Partnership"), false);
  assert.equal(mcaRegime("Partnership"), "none");
  // The reason is load-bearing: naming the wrong registrar would be a
  // plausible-sounding sentence that is legally false.
  const note = mcaScopeNote("Partnership");
  assert.ok(note, "a partnership must get an explanation, not silence");
  assert.match(note!, /Registrar of FIRMS/i);
  assert.match(note!, /Indian Partnership Act 1932/);
});

test("trusts, societies and individuals are outside the Companies Act too", () => {
  for (const t of ["Trust", "Society", "Individual"]) {
    assert.equal(hasMcaObligations(t), false, `${t} must not be offered MCA`);
    assert.equal(usesScheduleIII(t), false, `${t} must not be told "Schedule III"`);
  }
});

// ── The entities that do file the company forms ────────────────────────────

test("a private limited company has MCA obligations", () => {
  assert.equal(hasMcaObligations("Private Limited"), true);
  assert.equal(isCompaniesActCompany("Private Limited"), true);
  assert.equal(mcaRegime("Private Limited"), "companies-act");
  // Nothing to explain away — the workspace applies as-is.
  assert.equal(mcaScopeNote("Private Limited"), null);
});

test("a public limited company has MCA obligations", () => {
  assert.equal(hasMcaObligations("Public Limited"), true);
  assert.equal(isCompaniesActCompany("Public Limited"), true);
});

test("a One Person Company has MCA obligations", () => {
  // An OPC is a company under §2(62) of the Companies Act 2013 — it files
  // AOC-4 and (as MGT-7A) the annual return. Recognised here so that adding
  // it to clients.entity_type can never silently strip a real company of its
  // workspace.
  assert.equal(hasMcaObligations("One Person Company"), true);
  assert.equal(isCompaniesActCompany("One Person Company"), true);
  assert.equal(usesScheduleIII("One Person Company"), true);
  assert.equal(mcaRegime("OPC"), "companies-act");
});

test("a Section 8 company has MCA obligations", () => {
  assert.equal(isCompaniesActCompany("Section 8"), true);
  assert.equal(isCompaniesActCompany("Section 8 Company"), true);
});

// ── The LLP trap, from both sides ──────────────────────────────────────────

test("an LLP is NOT treated as a company for the Companies Act forms", () => {
  assert.equal(isCompaniesActCompany("LLP"), false);
  assert.equal(usesScheduleIII("LLP"), false);
  assert.equal(mcaRegime("LLP"), "llp-act");
});

test("an LLP still has MCA obligations — it is on the portal, under its own Act", () => {
  assert.equal(hasMcaObligations("LLP"), true);
  const note = mcaScopeNote("LLP");
  assert.ok(note, "an LLP must be told what it actually files");
  assert.match(note!, /Form 11/);
  assert.match(note!, /Form 8/);
  assert.match(note!, /Limited Liability Partnership Act 2008/);
  // The forms it does NOT file must not be offered to it as its own.
  assert.doesNotMatch(note!, /\bfiles AOC-4\b/);
});

// ── Schedule III ───────────────────────────────────────────────────────────

test("Schedule III is claimed only where the Companies Act binds it", () => {
  // Companies Act 2013 §129 read with Schedule III.
  assert.equal(usesScheduleIII("Private Limited"), true);
  assert.equal(usesScheduleIII("Public Limited"), true);
  for (const t of ["Proprietorship", "Partnership", "LLP", "Trust", "Society", "Individual"]) {
    assert.equal(usesScheduleIII(t), false, `Schedule III must not be claimed for ${t}`);
  }
});

// ── Input handling ─────────────────────────────────────────────────────────

test("an unknown or missing entity type asserts no Companies Act obligation", () => {
  // Fail closed: every value the schema permits is classified, so an
  // unrecognised string is drift, and drift is not evidence of a company.
  for (const t of [null, undefined, "", "   ", "Cooperative Society Ltd"]) {
    assert.equal(hasMcaObligations(t), false);
    assert.equal(usesScheduleIII(t), false);
  }
  const note = mcaScopeNote(null);
  assert.ok(note && /not recorded/.test(note), "an unrecorded type must say so, not guess");
});

test("entity types are matched case- and spacing-insensitively", () => {
  assert.equal(isCompaniesActCompany("  private   limited  "), true);
  assert.equal(isCompaniesActCompany("PRIVATE LIMITED"), true);
  assert.equal(mcaRegime("llp"), "llp-act");
});

test("the note names the entity type, so the page never has to guess it", () => {
  assert.match(mcaScopeNote("Proprietorship")!, /Proprietorship/);
  assert.match(mcaScopeNote("Society")!, /Society/);
});

// ── The schema and the module must not drift apart ─────────────────────────

test("every entity type the database permits is classified by the module", () => {
  // clients.entity_type is a CHECK constraint, so its value list is the
  // complete universe of client entity types. If someone adds one to the
  // schema without deciding its MCA regime here, "none" would be assumed for
  // it silently — and if that new type were a company, its CA would lose the
  // MCA workspace with no error anywhere. This test is the tripwire.
  const sql = fs.readFileSync(
    path.join(WEB, "..", "api", "migrations", "001_initial_schema.sql"), "utf8");
  const clientsTable = sql.slice(sql.indexOf("CREATE TABLE clients"));
  const check = clientsTable.slice(
    clientsTable.indexOf("entity_type TEXT NOT NULL CHECK"));
  const values = Array.from(
    check.slice(0, check.indexOf(")),")).matchAll(/'([^']+)'/g), (m) => m[1]);

  // Prove the parse found something before asserting over it — a selector
  // that matches nothing passes every test after it.
  assert.ok(values.length >= 8,
    `expected the clients.entity_type CHECK list, parsed ${JSON.stringify(values)}`);
  assert.ok(values.includes("Proprietorship") && values.includes("Private Limited"),
    `parsed the wrong constraint: ${JSON.stringify(values)}`);

  const CLASSIFIED: Record<string, string> = {
    "Proprietorship": "none",
    "Partnership": "none",
    "LLP": "llp-act",
    "Private Limited": "companies-act",
    "Public Limited": "companies-act",
    "Trust": "none",
    "Society": "none",
    "Individual": "none",
  };
  for (const v of values) {
    assert.ok(v in CLASSIFIED,
      `clients.entity_type permits "${v}", which lib/entityObligations.ts has not been ` +
      "told about — classify it there (and here) before shipping the migration");
    assert.equal(mcaRegime(v), CLASSIFIED[v], `regime for "${v}"`);
  }
});

// ── The rule has exactly one home ──────────────────────────────────────────

test("no page re-implements the entity check inline", () => {
  // A second copy drifts, and only one copy would be law. Every gate imports
  // the predicate; nothing else in app/ names a company entity type in a
  // comparison of its own.
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== "node_modules") walk(full); continue; }
      if (!/\.tsx?$/.test(e.name)) continue;
      const src = fs.readFileSync(full, "utf8");
      // `entity_type === "Private Limited"` and friends — a comparison, not a
      // <select> option list or a seed row.
      if (/(===|!==|\.includes\(|==)\s*["'](Private Limited|Public Limited|Proprietorship)["']/.test(src)) {
        offenders.push(path.relative(WEB, full));
      }
    }
  };
  walk(path.join(WEB, "app"));
  walk(path.join(WEB, "components"));
  assert.deepEqual(offenders, [],
    "these files compare an entity type directly — import lib/entityObligations.ts instead");
});
