// POST-A-124: the shared read cache (lib/cache/readCache.ts) is held by RULE, from the source.
//   node --experimental-strip-types --test scripts/the-read-cache-is-opt-in-and-never-feeds-a-write.test.ts
//
// 1. OPT-IN: the request layer and the Supabase client never import the cache, so no read is cached by being made.
// 2. A LISTED SET OF READERS: only the files named below call `readStale`/`cachedReport`/`getClientsStale`; a new one is added here with its reason, which
//    is the review that "this is a list a person returns to and nothing that must be current at a write reads it".
// 3. A STALE ANSWER IS NEVER A WRITE'S INPUT: the cached client list is read only by the Clients screen; no data-layer WRITE function reads the cache.
// 4. WHO AND WHEN: sign-out clears everything, an auth change binds the cache to the person, the screen that paints a stale list says when it was read, and
//    every write function of the client data layer forgets the family.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name.startsWith(".") || e.name === "out") continue;
    const rel = path.join(dir, e.name);
    if (e.isDirectory()) walk(rel, out);
    else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(rel);
  }
  return out;
}

/** The files that may read through the cache, and why each is safe. */
const READERS: Record<string, string> = {
  "app/clients/page.tsx": "the Clients list: a list a person returns to; the real read always follows and the screen says when the painted one was read",
  "lib/data/clients.ts": "defines getClientsStale; its own write functions forget the family",
  "lib/accounting/reportCache.ts": "the report TTL cache, a user of the shared store; cleared after a posting",
  "lib/cache/readCache.ts": "the store",
  "lib/auth/AuthContext.tsx": "does not read: it only empties the cache on sign-out and binds it to the signed-in person",
  "app/clients/[id]/accounting/page.tsx": "report screens through cachedReport (60 s, cleared by the screen's own postings)",
  "app/clients/[id]/sales/page.tsx": "report screens through cachedReport",
  "app/clients/[id]/accounting/journal/[entryId]/edit/_page.tsx": "clears reports after the edit",
  "components/customers/CustomerFormModal.tsx": "clears reports after the save",
};

const files = walk("app").concat(walk("components"), walk("lib"));
const importers = (needle: RegExp) => files.filter((f) => needle.test(strip(read(f)))).map((f) => f.split(path.sep).join("/"));

test("the request layer and the Supabase client do not import the cache: a read is cached only where its screen asks", () => {
  for (const f of ["lib/api/index.ts", "lib/supabase/client.ts", "lib/supabase/plainRestFetch.ts", "lib/supabase/selectAll.ts"]) {
    assert.ok(!/lib\/cache\/readCache|readCache/.test(strip(read(f))), `${f} imports the read cache, which makes every read cached`);
  }
});

test("only the listed files use the cache", () => {
  const users = importers(/readCache|reportCache|getClientsStale/).filter((f) => !f.endsWith(".test.ts"));
  const unlisted = users.filter((f) => !(f in READERS));
  assert.deepEqual(unlisted, [], `a file uses the read cache without being listed (and reviewed) in READERS: ${unlisted.join(", ")}`);
  for (const f of Object.keys(READERS)) assert.ok(fs.existsSync(path.join(WEB, f)), `${f} is listed but does not exist`);
});

test("the cached client list is read by the Clients screen alone", () => {
  assert.deepEqual(importers(/getClientsStale/).filter((f) => f !== "lib/data/clients.ts").sort(), ["app/clients/page.tsx"]);
});

test("the data layer's writes forget the client list, and no write function reads the cache", () => {
  const src = strip(read("lib/data/clients.ts"));
  for (const fn of ["createClient", "updateClient", "archiveClient", "restoreClient", "permanentDeleteClient"]) {
    const m = new RegExp(`export async function ${fn}\\b[\\s\\S]*?\\n}\\n`).exec(src);
    assert.ok(m, `${fn} not found`);
    assert.match(m![0], /forgetReads\("clients"\)/, `${fn} does not forget the cached client list`);
    assert.ok(!/readStale|getClientsStale|peekRead/.test(m![0]), `${fn} reads through the cache`);
  }
  assert.match(strip(read("app/clients/page.tsx")), /forgetReads\("clients"\)/, "the screen's own bulk import does not forget the list");
});

test("sign-out empties the cache, an auth change binds it to the person, and the screen says when a painted list was read", () => {
  const auth = strip(read("lib/auth/AuthContext.tsx"));
  assert.match(auth, /forgetReads\(\)/);
  assert.match(auth, /bindReadCacheToUser\(/);
  const page = read("app/clients/page.tsx");
  assert.match(page, /readAtText\(paintedFrom\)/);
  assert.match(page, /could not be refreshed, so it may not be current/);
});

test("the cache keeps nothing in browser storage", () => {
  assert.ok(!/localStorage|sessionStorage|indexedDB/.test(strip(read("lib/cache/readCache.ts"))));
});
