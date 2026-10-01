// Every *.test.ts in apps/web is type-checked, and CI runs the check (engineering-17).
// Run with: node --experimental-strip-types --test scripts/every-test-file-is-type-checked.test.ts
//
// WHY THIS IS A RULE AND NOT A LINE IN A CONFIG
//   tsconfig.json excludes **/*.test.ts and the suite runs on
//   `node --experimental-strip-types`, which ERASES types without checking them,
//   so the 318 test files were checked by nothing until tsconfig.test.json. That
//   file lists them with a glob — and a glob is a SPELLING of "every test file":
//   narrow it, move a test to a name it does not match, or rename the extension,
//   and a file drops out of the program while the job stays green.
//
//   So this asks TypeScript which files the program holds (`--listFilesOnly`) and
//   compares that with the files on disk. It does not read the glob.
//
//   The second half is the workflow. A config nobody runs checks nothing, and
//   frontend-ci.yml is what runs it; the step is found in the workflow's `run:`
//   lines with comments removed, so a comment that mentions the command cannot
//   satisfy it.
//
// NEGATIVE CONTROLS — each applied, then reverted:
//
//   | control                                                            | fails |
//   |--------------------------------------------------------------------|-------|
//   | narrow tsconfig.test.json's include to "lib/**/*.test.ts"          | 1     |
//   | delete the "Type check the test files" step from frontend-ci.yml   | 1     |
//   | pass a string where a test helper takes a number (tsc -p, not this)| tsc   |
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO = path.join(WEB, "..", "..");
const SKIP = new Set(["node_modules", ".next", "out", ".git"]);

function testFilesOnDisk(dir: string, found: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) testFilesOnDisk(full, found);
    else if (/\.test\.(ts|tsx|mts|cts)$/.test(entry.name)) found.push(full);
  }
  return found;
}

/** The files tsconfig.test.json's program actually holds, as TypeScript reports them. */
function filesInTheProgram(): Set<string> {
  const tsc = path.join(WEB, "node_modules", "typescript", "bin", "tsc");
  const run = spawnSync(
    process.execPath,
    [tsc, "-p", path.join(WEB, "tsconfig.test.json"), "--listFilesOnly"],
    { cwd: WEB, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  assert.equal(run.status, 0, `tsc --listFilesOnly failed:\n${run.stdout}\n${run.stderr}`);
  return new Set(
    run.stdout.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => path.resolve(l)),
  );
}

test("the walk finds the test files — otherwise every check below is about nothing", () => {
  const found = testFilesOnDisk(WEB);
  assert.ok(found.length > 100, `only ${found.length} test files found; the walk is broken`);
});

test("every test file on disk is in the program tsconfig.test.json type-checks", () => {
  const onDisk = testFilesOnDisk(WEB);
  const inProgram = filesInTheProgram();
  const missing = onDisk.filter((f) => !inProgram.has(path.resolve(f)))
    .map((f) => path.relative(WEB, f)).sort();
  assert.deepEqual(
    missing,
    [],
    "these test files are not type-checked by tsconfig.test.json — its `include` no " +
      "longer reaches them, so a wrong-typed argument in them would pass CI:\n  " +
      missing.join("\n  "),
  );
});

test("the program is the tests PLUS what they import, not the tests alone", () => {
  // A program of only *.test.ts would check each test against `any` wherever it
  // imports something. If the import graph is not followed, the check is hollow.
  const inProgram = [...filesInTheProgram()].map((f) => path.relative(WEB, f));
  const imported = inProgram.filter((f) => !f.includes("node_modules") && !/\.test\.ts$/.test(f));
  assert.ok(imported.length > 50,
    `only ${imported.length} non-test source files reached the program; imports are not followed`);
});

test("frontend-ci.yml runs the test type-check, and runs it as a step that can fail the job", () => {
  const raw = fs.readFileSync(path.join(REPO, ".github", "workflows", "frontend-ci.yml"), "utf8");
  const code = raw.split("\n").filter((l) => !l.trimStart().startsWith("#")).join("\n");
  assert.match(code, /run:\s*pnpm exec tsc -p tsconfig\.test\.json\s*$/m,
    "frontend-ci.yml has no step running `pnpm exec tsc -p tsconfig.test.json` — the tests " +
      "would be checked by nothing again");
  // It has to live in the job that installs dependencies and is gated on the
  // frontend scope, like the app's own type check beside it.
  const step = /- name: Type check the test files\n([\s\S]*?)(?=\n\s*- name:|\s*$)/.exec(code);
  assert.ok(step, "the step is not named 'Type check the test files'");
  assert.match(step[1], /needs\.scope\.outputs\.web == 'true'/);
  assert.doesNotMatch(step[1], /continue-on-error/, "a type check that cannot fail the job checks nothing");
});

test("the app's own tsconfig still leaves tests out, so `next build` is not asked to check them", () => {
  // The reason tests have their own program: tsconfig.json feeds the Next build,
  // and the tests use node:test, `.ts` import extensions and a newer target. If
  // this starts failing, tsconfig.test.json may have become redundant — say so
  // here rather than leaving two configs that do the same thing.
  const app = fs.readFileSync(path.join(WEB, "tsconfig.json"), "utf8");
  assert.match(app, /"exclude":\s*\[[^\]]*\*\*\/\*\.test\.ts/);
});
