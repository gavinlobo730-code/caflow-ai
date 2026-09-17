// s.234A and s.234B are the server's answer, and an unfiled return is not nil
// interest (IT-13).
//
// Run with:
//   node --experimental-strip-types --test scripts/what-being-late-costs-is-the-servers-answer.test.ts
//
// WHAT WAS WRONG
//     `POST /api/income-tax/interest/234ab` has computed both sections since
//     IT-13's first half — s.234A at 1% a month for filing late, s.234B at 1%
//     a month where advance tax plus TDS fell below 90% of the assessed tax,
//     with the s.139(1) due date resolved by `itr_due_date_for_client` rather
//     than taken from the caller — and NOTHING called it. The advance-tax
//     screen rendered exactly one figure, "Interest u/s 234C", while the
//     income-tax landing page promised the calculator would compute s.234B
//     too.
//
// THE REACHABILITY HALF IS PINNED IN PYTHON
//     `apps/api/tests/test_every_mounted_endpoint_has_a_way_in.py` counts
//     endpoints no screen reaches and refuses slack in its own budget, so
//     wiring this one up lowered `/api/income-tax` from 7 to 6 and it cannot
//     silently come unwired. What that ratchet cannot see is the two rules
//     below, which are about WHAT the screen sends.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
}

function sources(): { rel: string; body: string }[] {
  const out: { rel: string; body: string }[] = [];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name)) {
        out.push({ rel: path.relative(WEB, p), body: code(fs.readFileSync(p, "utf8")) });
      }
    }
  };
  for (const d of ["app", "components", "lib"]) walk(path.join(WEB, d));
  return out.sort((a, b) => a.rel.localeCompare(b.rel));
}

/** THE REQUEST ITSELF, not the file that contains it. A whole-file scan was
 *  the first draft and it failed on `lib/data/income-tax.ts`, whose RESPONSE
 *  type legitimately declares the `due_date` the server sends back — so what
 *  is read is the object literal each call actually passes. */
function requests(): { rel: string; body: string }[] {
  const out: { rel: string; body: string }[] = [];
  for (const { rel, body } of sources()) {
    let at = body.indexOf("computeSection234ABInterest(");
    while (at !== -1) {
      let i = body.indexOf("(", at), depth = 0, end = i;
      for (; end < body.length; end += 1) {
        if (body[end] === "(") depth += 1;
        else if (body[end] === ")") { depth -= 1; if (depth === 0) break; }
      }
      out.push({ rel, body: body.slice(i + 1, end) });
      at = body.indexOf("computeSection234ABInterest(", end);
    }
  }
  // The definition itself is one of the matches only if it calls itself, which
  // it does not — so a non-empty list means a real call site exists.
  assert.ok(out.some(r => /\{/.test(r.body)),
    "nothing builds a s.234A/s.234B request any more — this guard has gone vacuous");
  return out.filter(r => /\{/.test(r.body));
}

test("an unfiled return is sent as nothing, never as today", () => {
  // None means NOT YET FURNISHED, and the engine then runs the period to the
  // assessment date and says it is still running. Defaulting to today would
  // report nil interest for an unfiled return — telling a CA the cheapest
  // moment to file is never.
  for (const { rel, body } of requests()) {
    for (const m of body.matchAll(/return_furnished_on\s*:\s*([^,;\n}]*)/g)) {
      const v = m[1].trim();
      assert.ok(
        !/today|Date\s*\(|now\(/i.test(v),
        `${rel} sends return_furnished_on as ${v}. Blank means NOT YET FURNISHED, ` +
        "which is not the same as nil interest — defaulting it to today reports " +
        "zero s.234A for a return nobody has filed.",
      );
    }
  }
});

test("the s.139(1) due date is the server's, never the screen's", () => {
  // `itr_due_date_for_client` is the one authority, and it reports whether it
  // could decide at all. A screen sending its own date would be a second
  // implementation of Explanation 2 to s.139(1) — and the whole s.234A charge
  // hangs on that date.
  for (const { rel, body } of requests()) {
    assert.ok(
      !/\bdue_date\s*:/.test(body),
      `${rel} sends its own due_date with the s.234A/s.234B request. The date is ` +
      "derived server-side by itr_due_date_for_client, which also says whether " +
      "the statute settles it on the facts held — a screen cannot say that.",
    );
  }
});

test("no screen declares a s.234A or s.234B rate or period", () => {
  // The rate and the month count are the engine's. A browser copy of a s.234
  // computation is exactly what IT-06 deleted from this very screen.
  const RATE = /(234a|234b)[^\n]{0,80}(1\s*%|0?\.01\b|rate)/i;
  for (const { rel, body } of sources()) {
    if (!/234ab|section_234a|section_234b/.test(body)) continue;
    for (const line of body.split("\n")) {
      // A LABEL naming the section is what the screen is for; an arithmetic
      // rate beside it is the defect.
      if (RATE.test(line) && /[*/]|Math\./.test(line)) {
        assert.fail(
          `${rel} looks like it computes s.234A/s.234B interest itself:\n  ${line.trim()}\n` +
          "Both sections are the server's answer — render interest_paise, never derive it.",
        );
      }
    }
  }
});
