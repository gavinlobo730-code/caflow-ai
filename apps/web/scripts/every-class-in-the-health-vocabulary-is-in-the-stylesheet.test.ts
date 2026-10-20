// Every Tailwind class the health vocabulary names is in the built stylesheet.
//
// Run with:
//   node --experimental-strip-types --test scripts/every-class-in-the-health-vocabulary-is-in-the-stylesheet.test.ts
//
// WHAT WENT WRONG (found by the independent review of the health-vocabulary change)
//     Tailwind writes a utility only if its full name appears as a literal in a file named by `content` in `tailwind.config.ts`,
//     which listed `pages`, `components` and `app` and not `lib`. The grade bar classes (`bg-sev-ok` ... `bg-sev-critical`) moved
//     from two pages into `lib/health/vocabulary.ts` and so out of every scanned file: the dimension bars, the score dots and the
//     grade histogram on the Health screens would have shipped with no fill, while tsc, eslint and every other test passed. The
//     badge and text classes survived only because other scanned files happen to spell the same names.
//
// WHAT THIS DOES
//     Builds the stylesheet with the repository's own config and checks that every class in the vocabulary's three look tables
//     is emitted. It reads the tables out of the source, so a class added to a table is checked without touching this file.
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const VOCAB = path.join(WEB, "lib", "health", "vocabulary.ts");
const TABLES = ["GRADE_BADGE_CLASS", "GRADE_TEXT_CLASS", "GRADE_BAR_CLASS"];

function classesIn(table: string): string[] {
  const src = fs.readFileSync(VOCAB, "utf8");
  const body = new RegExp(`export const ${table}[^=]*=\\s*\\{([\\s\\S]*?)\\};`).exec(src);
  assert.ok(body, `${table} is gone from the vocabulary`);
  const values = [...body[1].matchAll(/"[A-Za-z ]+":\s*"([^"]+)"/g)].map((m) => m[1]);
  assert.equal(values.length, 5, `${table} no longer has one entry per grade`);
  return values.flatMap((v) => v.split(/\s+/)).filter(Boolean);
}

function builtStylesheet(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tailwind-guard-"));
  const input = path.join(dir, "input.css");
  fs.writeFileSync(input, "@tailwind utilities;\n");
  const bin = path.join(WEB, "node_modules", ".bin", "tailwindcss");
  return execFileSync(bin, ["-c", "tailwind.config.ts", "-i", input], { cwd: WEB, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
}

test("the config scans lib/health, where the vocabulary lives, and nothing wider", () => {
  const config = fs.readFileSync(path.join(WEB, "tailwind.config.ts"), "utf8");
  assert.match(config, /"\.\/lib\/health\/\*\*\/\*\.\{[^}]*ts[^}]*\}"/, "tailwind.config.ts does not scan ./lib/health, so a class written only there is dropped");
  assert.doesNotMatch(config, /"\.\/lib\/\*\*/, "tailwind.config.ts scans all of ./lib, which restyles screens that are not this vocabulary's (the sign-in splash in lib/auth)");
});

test("every class in the three look tables is emitted by the real build", () => {
  const css = builtStylesheet();
  assert.ok(css.length > 500, "the build produced no stylesheet");
  const missing: string[] = [];
  for (const table of TABLES) {
    for (const cls of new Set(classesIn(table))) {
      if (!new RegExp(`\\.${cls.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&")}(?![\\w-])`).test(css)) missing.push(`${table}: ${cls}`);
    }
  }
  assert.deepEqual(missing, [], `these classes are in the vocabulary but not in the stylesheet: ${missing.join(", ")}`);
});
