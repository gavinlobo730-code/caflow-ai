// A CSV this product writes survives a comma in a client's name.
//
// Run with:
//   node --experimental-strip-types --test scripts/one-csv-writer-and-it-escapes.test.ts
//
// WHAT WAS WRONG (T5b-5, measured 19 September 2026)
//     Thirteen files built a CSV. Seven escaped by hand, and two of those were
//     wrong in ways that corrupt the file without any error:
//
//       app/risks/page.tsx
//         [r.clientName, r.riskType, `"${r.description}"`, ...].join(",")
//         The client name and risk type were NOT QUOTED AT ALL, so a client
//         called "Sharma, Gupta & Co" shifted every column after it by one —
//         for that row only, so the file opened and one line of data sat under
//         the wrong headings.
//
//       app/accounting/receivables/page.tsx
//         row.map(v => `"${v}"`).join(",")
//         Wrapped every field in quotes and never doubled the ones inside, so
//         a narration carrying a quote ended its field early.
//
//     `app/payroll/statutory/page.tsx` and all three exports in
//     `app/payroll/reports/page.tsx` wrapped an employee NAME the same way.
//
//     The correct rule already existed — `csvCell` in lib/table/process.ts —
//     and was module-private. That is the whole mechanism: an implementation
//     nobody can reach is why there are seven others.
//
// TWO MORE LANDMINES THE SWEEP FOUND
//     `app/income-tax/ais/page.tsx` and `components/banking/BankBook.tsx` both
//     prepended a LITERAL U+FEFF typed into the source — invisible in every
//     editor and one stray keystroke from silently disappearing. And
//     `app/payroll/reports/page.tsx` declared a private
//     `downloadCsv(content, filename)`: the same name as the shared one with
//     the arguments the other way round, so a screen importing the shared one
//     and calling it by the local habit would have written a file named after
//     its own contents.
//
// THE RULE
//     `lib/export/csv.ts` is the only place a CSV field is escaped or a
//     text/csv Blob is made. The two GOVERNMENT UPLOAD paths are allowlisted
//     WITH their reason: the EPFO ECR is a fixed-format text file and the ESIC
//     CSV is uploaded to a portal, and a byte-order mark breaks the parse on
//     both — so they deliberately do not go through a writer that adds one.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { csvField, toCsvRows } from "../lib/export/csv.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const WRITER = "lib/export/csv.ts";

/** A government upload must NOT receive a BOM, so it may not use the writer. */
const UPLOADS_TO_A_PORTAL: Record<string, string> = {
  "app/payroll/page.tsx":
    "builds the EPFO ECR (fixed-format text) and the ESIC CSV; `downloadFile` " +
    "takes an explicit `bom` flag because extra bytes break the parse at the portal",
  "components/payroll/StatutoryHandoff.tsx":
    "saves bytes the SERVER built for the same two uploads; it composes no CSV at all",
};

function sourceFiles(): string[] {
  const out: string[] = [];
  for (const dir of ["app", "components", "lib"]) {
    const walk = (d: string) => {
      for (const e of fs.readdirSync(path.join(WEB, d), { withFileTypes: true })) {
        const rel = path.join(d, e.name);
        if (e.isDirectory()) walk(rel);
        else if (/\.(ts|tsx)$/.test(e.name)) out.push(rel);
      }
    };
    walk(dir);
  }
  return out;
}

/** Comments stripped — a guard that reads its own prose passes on a broken tree. */
function code(rel: string): string {
  return fs
    .readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

// ── the door ────────────────────────────────────────────────────────────────

test("the scan sees the whole frontend", () => {
  const files = sourceFiles();
  assert.ok(files.length > 200, `only ${files.length} source files found`);
  assert.ok(files.includes(WRITER), "the writer itself is not in the scan");
});

test("only the one writer makes a text/csv Blob", () => {
  const offenders = sourceFiles().filter(
    (f) => f !== WRITER && /text\/csv/.test(code(f)) && !(f in UPLOADS_TO_A_PORTAL),
  );
  assert.deepEqual(
    offenders,
    [],
    "these build a CSV outside lib/export/csv.ts, so the escaping and the BOM " +
      `are theirs to get right — and seven of them did not: ${offenders.join(", ")}`,
  );
});

test("nothing escapes a CSV field by hand", () => {
  const byHand = /replace\(\s*\/"\/g\s*,\s*['"]""/;
  const offenders = sourceFiles().filter((f) => f !== WRITER && byHand.test(code(f)));
  assert.deepEqual(
    offenders,
    [],
    `these double a quote themselves rather than calling csvField: ${offenders.join(", ")}`,
  );
});

test("the two portal uploads are still the only exemptions, and still say why", () => {
  for (const [file, why] of Object.entries(UPLOADS_TO_A_PORTAL)) {
    assert.ok(fs.existsSync(path.join(WEB, file)), `${file} has moved`);
    assert.ok(why.length > 40, `${file}'s exemption has no reason recorded`);
    assert.ok(
      /bom|byte/i.test(code(file)) || /bom|byte/i.test(fs.readFileSync(path.join(WEB, file), "utf8")),
      `${file} is exempt because a BOM breaks a portal parse and no longer says so`,
    );
  }
});

test("no source file carries a literal byte-order mark", () => {
  const offenders = sourceFiles().filter((f) =>
    fs.readFileSync(path.join(WEB, f), "utf8").includes("﻿"),
  );
  assert.deepEqual(
    offenders,
    [],
    "a U+FEFF typed into the source is invisible in every editor — write the " +
      `escape \\uFEFF instead: ${offenders.join(", ")}`,
  );
});

// ── the behaviour, which the door alone does not give ───────────────────────

test("a comma in a field does not become a column", () => {
  assert.equal(csvField("Sharma, Gupta & Co"), '"Sharma, Gupta & Co"');
  assert.equal(
    toCsvRows([["Client", "Amount"], ["Sharma, Gupta & Co", "1000.00"]]),
    'Client,Amount\n"Sharma, Gupta & Co",1000.00',
  );
});

test("a quote inside a field is doubled", () => {
  assert.equal(csvField('Ravi "Raj" Kumar'), '"Ravi ""Raj"" Kumar"');
});

test("a newline inside a field is quoted, not emitted raw", () => {
  assert.equal(csvField("line one\nline two"), '"line one\nline two"');
  assert.equal(csvField("carriage\rreturn"), '"carriage\rreturn"');
});

test("a leading or trailing space is preserved by quoting it", () => {
  // `csvCell` did not do this, and a name pasted with a trailing space came
  // back from a round trip different from the one in the books.
  assert.equal(csvField(" Acme "), '" Acme "');
});

test("an ordinary field is NOT quoted", () => {
  // Quoting everything is equally valid and would rewrite the bytes of every
  // export this product already produces.
  assert.equal(csvField("Acme Traders"), "Acme Traders");
  assert.equal(csvField("2026-06-10"), "2026-06-10");
});

test("nothing becomes an empty field, never the word null", () => {
  assert.equal(csvField(null), "");
  assert.equal(csvField(undefined), "");
  assert.equal(toCsvRows([["a", null, "b"]]), "a,,b");
});

test("a number goes out bare, with no grouping and no rupee mark", () => {
  // A CSV cell exists to be parsed. The workbook wants the opposite — a number
  // carrying an Indian FORMAT — which is why the two modules cannot share one.
  assert.equal(csvField(1234567.89), "1234567.89");
  assert.equal(csvField(0), "0");
});
