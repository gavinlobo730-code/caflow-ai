// apex-overview-practice-07(d): the client Knowledge Base search fired a
// request on EVERY KEYSTROKE (an effect keyed on `query`, no debounce) and a
// separate Enter-key handler fired `load()` again on top — a stale-response
// race where an earlier, slower keystroke's response could overwrite a
// later, faster keystroke's results.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const PAGE = path.resolve(import.meta.dirname, "..", "app", "clients", "[id]", "knowledge", "page.tsx");

function read(): string {
  return fs.readFileSync(PAGE, "utf8");
}

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

test("the query-driven effect debounces with a real timer (setTimeout + clearTimeout cleanup)", () => {
  const code = stripComments(read());
  assert.match(code, /setTimeout\(\(\) => load\(query\), 300\)/,
    "no 300ms debounce around load(query) was found");
  assert.match(code, /return \(\) => clearTimeout\(timer\)/,
    "the debounce timer is not cleared on the next effect run/unmount — " +
    "without this, every keystroke still schedules a load that fires");
});

test("there is no bare `useEffect(() => { load(); }, [load])` re-running on every load() identity change", () => {
  const code = stripComments(read());
  assert.doesNotMatch(code, /useEffect\(\(\)\s*=>\s*\{\s*load\(\);?\s*\}\s*,\s*\[load\]\)/,
    "the old undebounced effect (fires whenever `load`'s identity changes, " +
    "i.e. every keystroke since it used to close over `query`) is still here");
});

test("the Enter-key handler on the search input is gone", () => {
  const code = stripComments(read());
  assert.doesNotMatch(code, /onKeyDown=\{.*Enter.*load\(/s,
    "an Enter-key handler still calls load() directly — the debounced " +
    "effect already covers every keystroke, Enter included");
});

test("load() takes the query text explicitly and only applies a response that still matches the current input (stale-response guard)", () => {
  const code = stripComments(read());
  assert.match(code, /const load = useCallback\(async \(q: string\)/,
    "load() no longer takes the query it was asked to search for as an " +
    "explicit argument — without it there is nothing to compare a late " +
    "response's query against");
  // The three places load() actually applies its result/error/loading state
  // must each be gated on the query still being current.
  const guardCount = (code.match(/latestQuery\.current === q/g) ?? []).length;
    assert.ok(guardCount >= 3,
    `found only ${guardCount} stale-response guard(s); setArticles, setError ` +
    `and setLoading(false) inside load() should each be gated`);
});

test("every caller of load() after the fix passes the current query, never a bare load with no argument", () => {
  const code = stripComments(read());
  // `load(query)` (refresh button, create-article success) or `load(q)`
  // (the internal call inside the debounce/effect) are both fine; a bare
  // `load()` or `load` used as an event handler directly is not, because
  // load's first parameter is now required.
  assert.doesNotMatch(code, /\bload\(\)/, "a bare load() call with no query argument was found");
  assert.doesNotMatch(code, /onClick=\{load\}/, "load is still passed directly as an event handler (would receive the click event as its query argument)");
});
