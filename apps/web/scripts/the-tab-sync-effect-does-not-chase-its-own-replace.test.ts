/**
 * The accounting page's tab/URL sync effect used to depend on `[urlTab, tab]`
 * (apex-accounting-reports-12). `setTab` updates `tab` SYNCHRONOUSLY on the
 * next render, but `router.replace` updates `useSearchParams()`
 * ASYNCHRONOUSLY, so the render right after a click saw the NEW `tab` next
 * to the STILL-OLD `urlTab` — the effect read that as an external change,
 * reverted `tab` back to `urlTab`, and the click's own state update then
 * re-advanced it, remounting every tab component (and firing every mounted
 * tab's data fetches) two or three times per click.
 *
 * THE RULE
 *
 *   The effect depends on `urlTab` ALONE, and compares against a REF (the
 *   tab this page itself last set) rather than the `tab` state variable —
 *   so it reacts only to a genuinely external URL change (back/forward, a
 *   deep link), never its own pending `replace()`.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const FILE = join(import.meta.dirname, "..", "app/clients/[id]/accounting/page.tsx");

function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

function tabSyncEffectBody(src: string): string {
  const marker = 'const [tab, setTabState] = useState<AccountingTab>(';
  const start = src.indexOf(marker);
  assert.ok(start >= 0, "expected to find the tab state declaration");
  const end = src.indexOf("const setTab = useCallback(", start);
  assert.ok(end > start, "expected to find setTab right after the sync effect");
  return src.slice(start, end);
}

test("the tab/URL sync effect's dependency array is [urlTab] only", () => {
  const src = code(readFileSync(FILE, "utf8"));
  const body = tabSyncEffectBody(src);
  assert.doesNotMatch(
    body, /\}, \[urlTab, tab\]\)/,
    "the effect must not depend on [urlTab, tab] — tab updates synchronously " +
    "while useSearchParams() updates asynchronously, so this dependency makes " +
    "the effect fire on the render right after every setTab() call and revert " +
    "the tab it was just given, causing a remount storm.",
  );
  assert.match(
    body, /\}, \[urlTab\]\)/,
    "the effect must depend on [urlTab] alone.",
  );
});

test("the effect compares urlTab against a ref, not the tab state variable", () => {
  const src = code(readFileSync(FILE, "utf8"));
  const body = tabSyncEffectBody(src);
  assert.match(
    body, /useRef\(tab\)/,
    "expected a ref seeded from tab (tracking the tab this page itself last set)",
  );
  assert.match(
    body, /urlTab !== tabRef\.current/,
    "the effect must compare urlTab against tabRef.current, not against the " +
    "tab state variable directly — comparing against tab is what reintroduces " +
    "the remount bug.",
  );
});
