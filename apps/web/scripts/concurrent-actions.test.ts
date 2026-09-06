// The one-action-at-a-time ratchet.
//
// Found by using the product: the bank-import dialog showed "Reading…" and
// "Importing…" at the same time, because each button was disabled only by its
// OWN in-flight flag. Two requests then run together and fight over one screen
// — and on that screen one of them was a WRITE to the client's books.
//
// Same two-part shape as loading-flags.test.ts: first prove the analysis tells
// the cases apart, then assert the app has none left. A ratchet on a number
// nobody trusts is worse than no ratchet.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { findConcurrentActions } from "./concurrent-actions.ts";
import { sourceFilesUnder } from "./await-waterfalls.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

const TWO_ACTIONS = (guardA: string, guardB: string) => `
export function Screen() {
  const [saving, setSaving] = useState(false);
  const [computing, setComputing] = useState(false);
  async function save() { setSaving(true); try { await api.save(); } finally { setSaving(false); } }
  async function compute() { setComputing(true); try { await api.compute(); } finally { setComputing(false); } }
  return (<div>
    <button onClick={save} disabled={${guardA}}>Save</button>
    <button onClick={compute} disabled={${guardB}}>Compute</button>
  </div>);
}`;

test("two actions each guarding only themselves is the bug", () => {
  const found = findConcurrentActions(TWO_ACTIONS("saving", "computing"));
  assert.equal(found.length, 2);
  assert.deepEqual(found[0].missing, ["computing"]);
  assert.deepEqual(found[1].missing, ["saving"]);
});

test("a shared derived flag is the fix", () => {
  assert.deepEqual(findConcurrentActions(
    TWO_ACTIONS("saving || computing", "saving || computing")), []);
});

test("one action guarding itself is not a bug", () => {
  assert.deepEqual(findConcurrentActions(`
    export function Screen() {
      const [saving, setSaving] = useState(false);
      async function save() { setSaving(true); try { await api.save(); } finally { setSaving(false); } }
      return <button onClick={save} disabled={saving}>Save</button>;
    }`), []);
});

test("flags in DIFFERENT components are not each other's business", () => {
  // The crude first version of this analysis grouped by file and claimed one
  // component's flag should guard another's button. They cannot see each other.
  assert.deepEqual(findConcurrentActions(`
    export function A() {
      const [saving, setSaving] = useState(false);
      async function save() { setSaving(true); try { await api.save(); } finally { setSaving(false); } }
      return <button onClick={save} disabled={saving}>Save</button>;
    }
    export function B() {
      const [computing, setComputing] = useState(false);
      async function compute() { setComputing(true); try { await api.go(); } finally { setComputing(false); } }
      return <button onClick={compute} disabled={computing}>Compute</button>;
    }`), []);
});

test("a copied-to-clipboard toast is not an action", () => {
  // Lowered by a timer, so it is feedback rather than work. Making other
  // buttons wait on it would disable the page for two seconds after copying a
  // link — a worse bug than the one this rule is for.
  assert.deepEqual(findConcurrentActions(`
    export function Screen() {
      const [copied, setCopied] = useState(false);
      const [saving, setSaving] = useState(false);
      async function copy() { await navigator.clipboard.writeText(x); setCopied(true); setTimeout(() => setCopied(false), 2000); }
      async function save() { setSaving(true); try { await api.save(); } finally { setSaving(false); } }
      return (<div>
        <button onClick={copy} disabled={copied}>Copy</button>
        <button onClick={save} disabled={saving}>Save</button>
      </div>);
    }`), []);
});

test("an action nothing can click is not reachable and not counted", () => {
  // A flag raised only by a useEffect loader has no button to press twice.
  assert.deepEqual(findConcurrentActions(`
    export function Screen() {
      const [loading, setLoading] = useState(false);
      const [saving, setSaving] = useState(false);
      async function load() { setLoading(true); try { await api.list(); } finally { setLoading(false); } }
      async function save() { setSaving(true); try { await api.save(); } finally { setSaving(false); } }
      useEffect(() => { void load(); }, []);
      return <button onClick={save} disabled={saving}>Save</button>;
    }`), []);
});

test("a flag derived from both counts as guarding both", () => {
  // The fix itself: `const actionInFlight = saving || computing;` on every
  // button. A rule that could not see through that would reject its own
  // remedy and demand the raw flags be repeated beside it.
  assert.deepEqual(findConcurrentActions(`
    export function Screen() {
      const [saving, setSaving] = useState(false);
      const [computing, setComputing] = useState(false);
      const actionInFlight = computing || saving;
      async function save() { setSaving(true); try { await api.save(); } finally { setSaving(false); } }
      async function compute() { setComputing(true); try { await api.go(); } finally { setComputing(false); } }
      return (<div>
        <button onClick={save} disabled={actionInFlight}>Save</button>
        <button onClick={compute} disabled={actionInFlight || !ready}>Compute</button>
      </div>);
    }`), []);
});

// ─── the ratchet ────────────────────────────────────────────────────────────

test("no screen can start a second action while one is running", () => {
  const found: string[] = [];
  for (const dir of ["app", "components"]) {
    for (const file of sourceFilesUnder(path.join(WEB, dir), fs, path)) {
      const rel = path.relative(WEB, file);
      for (const f of findConcurrentActions(fs.readFileSync(file, "utf8"))) {
        found.push(`${rel}:${f.line} ${f.component}.${f.fn} guards ${f.guards}, ignores ${f.missing.join(", ")}`);
      }
    }
  }
  assert.deepEqual(found.sort(), [],
    "A button starts one action while another is still running. The two " +
    "requests fight over the same screen, and the second can act on what the " +
    "first is still changing. Derive one flag from all of them — " +
    "`const actionInFlight = a || b;` — and disable every action button on " +
    "it:\n  " + found.join("\n  "));
});

test("the ratchet is reading the app, not an empty directory", () => {
  const files = ["app", "components"].flatMap((d) =>
    sourceFilesUnder(path.join(WEB, d), fs, path));
  assert.ok(files.length > 250, `only ${files.length} source files walked`);
});
