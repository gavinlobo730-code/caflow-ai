// apex-overview-practice-07 (item 6's code half): the Overview page's load
// effect used to depend on `financialYear`, although nothing inside that
// effect's body reads it — `ClientTimeline` already takes `financialYear` as
// its own prop and reloads its own feed on change. So changing the Activity
// FY picker re-ran the WHOLE overview fetch (client, tasks, compliance
// calendar, the health score — the heaviest call on the page) and dropped
// all fifteen hub tiles to a skeleton for several seconds, to satisfy a feed
// that needed none of it reloaded.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const PAGE = path.resolve(import.meta.dirname, "..", "app", "clients", "[id]", "overview", "page.tsx");

function read(): string {
  return fs.readFileSync(PAGE, "utf8");
}

// The effect that fetches client/tasks/compliance/health starts at
// `useEffect(() => {` right after the `reloadKey` state declaration and ends
// at its own dependency array — isolate exactly that block so a match
// elsewhere in the file (e.g. inside ClientTimeline's own prop wiring)
// cannot produce a false pass.
function loadEffectBody(src: string): string {
  const start = src.indexOf("useEffect(() => {");
  assert.ok(start > -1, "could not find the load effect at all");
  const end = src.indexOf("}, [clientId", start);
  assert.ok(end > -1, "could not find the load effect's own dependency array");
  return src.slice(start, end + 40);
}

test("the load effect's own body never reads financialYear", () => {
  const block = loadEffectBody(read());
  const body = block.slice(0, block.lastIndexOf("}, ["));
  // Strip comments first — the fix's own explanatory comment (right after
  // the dependency array, so outside `body` already, but a future edit could
  // move one inside) legitimately names financialYear without READING it.
  const code = body
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
  assert.doesNotMatch(code, /financialYear/,
    "the effect body reads financialYear — if that becomes true, it belongs " +
    "back in the dependency array and this test's premise is wrong");
});

test("financialYear is not in the load effect's dependency array", () => {
  const block = loadEffectBody(read());
  const depsMatch = block.match(/\}, \[([^\]]*)\]/);
  assert.ok(depsMatch, "could not find the dependency array");
  const deps = depsMatch[1].split(",").map((d) => d.trim()).filter(Boolean);
  assert.ok(!deps.includes("financialYear"),
    `financialYear is still in the dependency array: [${deps.join(", ")}]`);
  assert.ok(deps.includes("clientId"), "clientId should still be a dependency");
});

test("ClientTimeline still receives financialYear as its own prop (the feed still scopes by year)", () => {
  const src = read();
  assert.match(src, /<ClientTimeline\s+clientId=\{clientId\}\s+financialYear=\{financialYear\}\s*\/>/,
    "ClientTimeline no longer receives financialYear — the Activity feed " +
    "would stop being year-scoped entirely, which is a different (worse) bug");
});

test("Hub is still mounted on this page (unrelated to this fix, but a sane sanity check)", () => {
  const src = read();
  assert.match(src, /<Hub\b/);
});
