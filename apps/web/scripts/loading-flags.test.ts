// The stranded-loading-flag ratchet. Run with:
//   node --experimental-strip-types --test scripts/loading-flags.test.ts
//
// Same two-part shape as await-waterfalls.test.ts. The first half proves the
// analysis distinguishes the cases that matter — a guard clause is not a bug, a
// synchronous toggle is not a bug, a flag lowered in a `finally` is the fix —
// because a ratchet on a number nobody trusts is worse than no ratchet.
//
// The second half walks the app and asserts the exact set of remaining
// violations. Not "no more than": exactly, so an entry that stops being true
// has to be deleted rather than quietly kept.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { findStrandedFlags } from "./loading-flags.ts";
import { sourceFilesUnder } from "./await-waterfalls.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

/**
 * Flags allowed to stay raised on one path, with the reason.
 *
 * Both entries are the same case: a sign-in form that leaves its button
 * disabled while the router navigates away, so the form cannot be submitted
 * twice during the redirect. Every FAILING path lowers the flag; only the
 * success path holds it, and on that path the component unmounts.
 *
 * Keyed by file. Each of these files has exactly one such function, so the key
 * is precise today; if a second violation ever appears in one of them, that is
 * a reason to split the key, not to widen the entry.
 *
 * This map may shrink. Adding to it means accepting a screen that can hang.
 */
const ALLOWED: Record<string, string> = {
  "app/login/page.tsx":
    "handleMfaSubmit keeps the button disabled while router.push() runs, so a " +
    "verified code cannot be submitted twice mid-redirect. Every error path " +
    "lowers it.",
  "app/portal/login/page.tsx":
    "Same as app/login/page.tsx — the success path navigates away and holds " +
    "the flag to block a double submit.",
};

// ─── the analysis itself ────────────────────────────────────────────────────

function hits(source: string) {
  return findStrandedFlags("t.tsx", source);
}

test("flags a loader that lowers its flag only on the happy path", () => {
  const found = hits(`
    async function load() {
      setLoading(true);
      const { data } = await supabase.from("customers").select("*");
      setCustomers(data);
      setLoading(false);
    }
  `);
  assert.equal(found.length, 1);
  assert.equal(found[0].flag, "setLoading");
});

test("a flag lowered in a finally is not flagged", () => {
  assert.deepEqual(hits(`
    async function load() {
      setLoading(true);
      try {
        const { data } = await supabase.from("customers").select("*");
        setCustomers(data);
      } finally {
        setLoading(false);
      }
    }
  `), []);
});

test("a trailing lower after try/catch is still flagged", () => {
  // Works today and is why so many of these went unnoticed — but a `throw`
  // from inside the catch, or a `return` added inside the try later, skips it.
  const found = hits(`
    async function load() {
      setLoading(true);
      try {
        setRows(await api.list());
      } catch {
        setFailed(true);
      }
      setLoading(false);
    }
  `);
  assert.equal(found.length, 1);
});

test("a guard clause that lowers the flag early is not itself a violation", () => {
  // `if (!clientId) { setLoading(false); return; }` is correct code. What
  // matters is whether the AWAIT path is covered, and here it is.
  assert.deepEqual(hits(`
    async function load() {
      if (!clientId) { setLoading(false); return; }
      setLoading(true);
      try {
        setRows(await api.list());
      } finally {
        setLoading(false);
      }
    }
  `), []);
});

test("a synchronous function is not flagged", () => {
  // With no await there is nothing that can reject and skip the lowering.
  assert.deepEqual(hits(`
    function toggle() {
      setLoading(true);
      setRows([]);
      setLoading(false);
    }
  `), []);
});

test("a flag that is raised and never lowered is left to a different rule", () => {
  // A permanent spinner by construction — a real bug, but not this one, and
  // reporting it here would suggest adding a finally is the fix when the
  // function has nothing to put in it.
  assert.deepEqual(hits(`
    async function load() {
      setLoading(true);
      setRows(await api.list());
    }
  `), []);
});

test("each flag in a function is judged on its own", () => {
  // setSaving is safe, setBusy is not. Reporting the function as a whole would
  // hide which one needs the fix.
  const found = hits(`
    async function save() {
      setSaving(true);
      setBusy(true);
      try {
        await api.save();
        setBusy(false);
      } finally {
        setSaving(false);
      }
    }
  `);
  assert.deepEqual(found.map((f) => f.flag), ["setBusy"]);
});

test("a nested callback's own flag does not count as the outer function's", () => {
  // The outer function raises and lowers nothing; the inner arrow does both.
  const found = hits(`
    async function outer() {
      await Promise.all(rows.map(async (r) => {
        setBusy(true);
        await api.save(r);
        setBusy(false);
      }));
    }
  `);
  assert.equal(found.length, 1, "the inner function's own violation should be reported once");
});

// ─── the ratchet ────────────────────────────────────────────────────────────

test("no screen can be left stranded on its loading state", () => {
  const found = new Map<string, string[]>();
  for (const dir of ["app", "components", "lib"]) {
    for (const file of sourceFilesUnder(path.join(WEB, dir), fs, path)) {
      const rel = path.relative(WEB, file);
      for (const f of findStrandedFlags(file, fs.readFileSync(file, "utf8"))) {
        const list = found.get(rel) ?? [];
        list.push(`line ${f.line}: ${f.flag}`);
        found.set(rel, list);
      }
    }
  }

  const unexpected = [...found.keys()].filter((f) => !(f in ALLOWED)).sort();
  assert.deepEqual(
    unexpected, [],
    "A loading flag can be left raised. If the awaited call rejects, the " +
    "screen keeps its skeleton (or its Save button stays disabled) until the " +
    "page is reloaded — lower the flag in a `finally`, or add the file to " +
    "ALLOWED with the reason it has to stay:\n" +
    unexpected.map((f) => `  ${f}\n    ${(found.get(f) ?? []).join("\n    ")}`).join("\n"),
  );

  const stale = Object.keys(ALLOWED).filter((f) => !found.has(f)).sort();
  assert.deepEqual(
    stale, [],
    "ALLOWED lists file(s) that no longer strand a flag — delete these " +
    "entries so the list keeps meaning something: " + stale.join(", "),
  );
});

test("the ratchet is actually reading the app, not an empty directory", () => {
  const files = ["app", "components", "lib"].flatMap((d) =>
    sourceFilesUnder(path.join(WEB, d), fs, path));
  assert.ok(files.length > 300, `only ${files.length} source files walked`);
  assert.ok(files.some((f) => f.endsWith(path.join("clients", "[id]", "payroll", "page.tsx"))));
});
