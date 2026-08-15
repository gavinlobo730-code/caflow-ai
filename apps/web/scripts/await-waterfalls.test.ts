// The request-waterfall ratchet. Run with:
//   node --experimental-strip-types --test scripts/await-waterfalls.test.ts
//
// Two jobs. The first half proves the analysis is right — that it finds a real
// waterfall, and that it does NOT flag the four shapes that look like one and
// are not (a genuine data dependency, a guard between the two calls, the arms
// of an if/else, and calls in two different functions). Without those the
// second half would be a ratchet on a number nobody trusts.
//
// The second half walks the whole app and asserts the set of waterfalls is
// exactly EXPECTED. Not "no more than" — exactly, so removing one without
// removing its entry here fails too, and the list cannot rot into a wishlist.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { findWaterfalls, sourceFilesUnder } from "./await-waterfalls.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

/**
 * Waterfalls that are allowed to stay, each with the reason it is not a bug.
 * Keyed by repo-relative path; the value is a note for whoever reads a failure.
 *
 * This map may shrink. Adding to it means accepting another round trip, so an
 * addition needs a reason of the same kind as the ones already here.
 */
const ALLOWED: Record<string, string> = {
  "app/client-portal/page.tsx":
    "Delete a stored file, then delete the row that points at it. Ordering is " +
    "the point: if the row went first and the storage delete failed, the file " +
    "would be orphaned with nothing left referencing it. One user action, not " +
    "a page load.",
  "app/clients/[id]/documents/page.tsx":
    "Same storage-then-row delete as app/client-portal/page.tsx.",
  "app/clients/documents/page.tsx":
    "Same storage-then-row delete as app/client-portal/page.tsx.",
};

// ─── the analysis itself ────────────────────────────────────────────────────

function hits(source: string) {
  return findWaterfalls("t.tsx", source);
}

test("flags two independent calls awaited one after the other", () => {
  const found = hits(`
    async function load() {
      const a = await api.one();
      const b = await api.two();
      use(a, b);
    }
  `);
  assert.equal(found.length, 1);
});

test("does not flag a call that consumes the previous result", () => {
  assert.deepEqual(hits(`
    async function load() {
      const first = await api.one();
      const second = await api.two(first.id);
    }
  `), []);
});

test("does not flag a call the previous result guards", () => {
  // Hoisting the second call above this guard would fire a request the code
  // deliberately chose not to make.
  assert.deepEqual(hits(`
    async function load() {
      const res = await api.one();
      if (!res.success) return;
      const other = await api.two();
    }
  `), []);
});

test("does not flag the two arms of an if/else", () => {
  assert.deepEqual(hits(`
    async function load(isCredit) {
      if (isCredit) {
        const a = await supabase.from("customers").select("id");
        use(a);
      } else {
        const b = await supabase.from("vendors").select("id");
        use(b);
      }
    }
  `), []);
});

test("does not flag calls that live in different functions", () => {
  assert.deepEqual(hits(`
    function Page() {
      async function load() { const a = await api.one(); use(a); }
      async function save() { const b = await api.two(); use(b); }
    }
  `), []);
});

test("does not flag a conditional call and the one after it", () => {
  assert.deepEqual(hits(`
    async function run(t) {
      if (t.category) await api.banking.categorize(t.id);
      if (t.accountId) await api.banking.setAccount(t.id);
    }
  `), []);
});

test("counts await Promise.all as a single step", () => {
  assert.deepEqual(hits(`
    async function load() {
      const [a, b] = await Promise.all([api.one(), api.two()]);
      use(a, b);
    }
  `), []);
});

test("sees a Supabase chain whose dot is on the next line", () => {
  // The bug that made the second draft of this analysis report zero findings on
  // the file it was written for: /supabase\\./ does not match "supabase\\n.from".
  // Most chains in this app are written exactly this way.
  const found = hits(`
    async function load() {
      const { count } = await supabase
        .from("bank_transactions")
        .select("id", { count: "exact", head: true });
      const { data } = await supabase
        .from("journal_entries")
        .select("id");
      use(count, data);
    }
  `);
  assert.equal(found.length, 1, "a multi-line Supabase chain was invisible");
});

test("treats a reassigned outer variable as a dependency", () => {
  // `session` is assigned, not declared, in the first statement. A binding
  // analysis that only looked at `const`/`let` would call these independent
  // and suggest firing the fetch before there was a token to send.
  assert.deepEqual(hits(`
    async function load() {
      let session = null;
      session = await supabase.auth.getSession();
      const res = await fetch(url, { headers: { Authorization: session.token } });
    }
  `), []);
});

test("ignores awaits that are not network calls", () => {
  assert.deepEqual(hits(`
    async function load() {
      await sleep(10);
      await tick();
    }
  `), []);
});

// ─── the ratchet ────────────────────────────────────────────────────────────

test("no page or component gained a new request waterfall", () => {
  const found = new Map<string, string[]>();
  for (const dir of ["app", "components", "lib"]) {
    for (const file of sourceFilesUnder(path.join(WEB, dir), fs, path)) {
      const rel = path.relative(WEB, file);
      for (const w of findWaterfalls(file, fs.readFileSync(file, "utf8"))) {
        const list = found.get(rel) ?? [];
        list.push(`${w.line} then ${w.nextLine}: ${w.first}`);
        found.set(rel, list);
      }
    }
  }

  const unexpected = [...found.keys()].filter((f) => !(f in ALLOWED)).sort();
  assert.deepEqual(
    unexpected, [],
    "New request waterfall(s). Two network calls run one after the other with " +
    "nothing linking them, so the screen waits for both in series — put them " +
    "in one Promise.all, or add the file to ALLOWED with the reason it has " +
    "to stay:\n" +
    unexpected.map((f) => `  ${f}\n    ${(found.get(f) ?? []).join("\n    ")}`).join("\n"),
  );

  const stale = Object.keys(ALLOWED).filter((f) => !found.has(f)).sort();
  assert.deepEqual(
    stale, [],
    "ALLOWED lists file(s) that no longer have a waterfall — delete these " +
    "entries so the list keeps meaning something: " + stale.join(", "),
  );
});

test("the ratchet is actually reading the app, not an empty directory", () => {
  // Vacuity guard. If sourceFilesUnder ever returned [], the assertion above
  // would pass while checking nothing at all.
  const files = ["app", "components", "lib"].flatMap((d) =>
    sourceFilesUnder(path.join(WEB, d), fs, path));
  assert.ok(files.length > 300, `only ${files.length} source files walked`);
  assert.ok(files.some((f) => f.endsWith(path.join("clients", "[id]", "sales", "page.tsx"))));
});
