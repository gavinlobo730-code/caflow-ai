// The two GSTR-3B screens show the same return (GST-22).
//
// Run with:
//   node --experimental-strip-types --test scripts/both-gstr3b-screens-show-the-same-return.test.ts
//
// WHAT WAS WRONG
//     `POST /api/gst/gstr3b/from-books` returns three things that are part of
//     the face of the return and are not figures: `late_filing` (Table 5.1 —
//     what being late costs), `bank_line_caveats` with the bank totals inside
//     `reconciliation` (what the lines a CA marked as carrying GST put on the
//     return), and `undeclarable_rows` (the rows filed NIL because nothing here
//     can derive them, where a nil meaning "this client had none" and a nil
//     meaning "we cannot see it" are indistinguishable once filed).
//
//     The per-client GST tab spelled all three out inline. `computeGSTR3B`
//     DROPPED the keys on the way through, so the firm-level `/gst/gstr3b`
//     screen showed none of them — two screens disagreeing about how much of
//     the return they show, which is the same defect one level up as the
//     figures the engine got right and no screen rendered.
//
// TWO RULES, BOTH DURABLE
//     A screen that computes a GSTR-3B renders the component; and the sentences
//     live in the component, so a second copy cannot drift from the first. The
//     panels are matched by the WORDS a CA reads, not by a component name — a
//     re-implementation under a different name is exactly what this is about.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const COMPONENT = path.join("components", "gst", "Gstr3bFindings.tsx");

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

/** Anything that asks the server to compute a GSTR-3B from the books. */
const COMPUTES = /gstr3b\/from-books|computeGSTR3B\s*\(/;

test("every screen that computes a GSTR-3B renders the findings", () => {
  const screens = sources().filter(({ rel, body }) =>
    rel.startsWith("app" + path.sep) && COMPUTES.test(body));
  assert.ok(screens.length >= 2,
    `expected both GSTR-3B screens, found ${screens.length} — this guard has gone vacuous`);
  for (const { rel } of screens) {
    const body = fs.readFileSync(path.join(WEB, rel), "utf8");
    assert.match(body, /<Gstr3bFindings\b/,
      `${rel} computes a GSTR-3B and renders none of what the return says beyond the ` +
      "figures. Render <Gstr3bFindings /> — the sentences are the server's and both " +
      "screens must show the same return.");
  }
});

test("the panels are written once", () => {
  // The words a CA reads, not the component's name.
  const PHRASES = [
    "Nil because this product cannot derive it",
    "From bank lines you marked as carrying GST",
    "interest at 18% on the cash payable",
  ];
  for (const phrase of PHRASES) {
    const owners = sources().filter(({ body }) => body.includes(phrase)).map((f) => f.rel);
    assert.deepEqual(owners, [COMPONENT],
      `"${phrase}" is written in ${owners.join(", ") || "nothing"}. It belongs in ` +
      `${COMPONENT} alone — two copies of a panel is how the two GSTR-3B screens came ` +
      "to disagree in the first place.");
  }
});

test("the data layer carries what the screens render", () => {
  // `computeGSTR3B` re-shapes the response, and a key it does not copy reaches
  // no screen however well the component renders it. That IS the defect: the
  // firm-level screen was rendering nothing because the shaper dropped these
  // four, not because the panel was missing.
  const gst = fs.readFileSync(path.join(WEB, "lib", "data", "gst.ts"), "utf8");
  const shaper = gst.slice(gst.indexOf("const shaped: GSTR3BComputeResult"));
  for (const key of ["late_filing", "undeclarable_rows", "bank_line_caveats", "reconciliation"]) {
    assert.match(shaper.slice(0, 1200), new RegExp(`\\b${key}:`),
      `computeGSTR3B drops \`${key}\`, so no screen can show it.`);
  }
});
