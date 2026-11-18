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
  "components/customers/CustomerFormModal.tsx": "clears reports after the save, and forgets the customer lists",
  "lib/data/partyLists.ts": "defines the customer and supplier list readers and their forgets",
  "app/clients/[id]/purchases/page.tsx": "the Vendors tab paints its last list; its own supplier writes forget the family",
  "app/accounting/suppliers/page.tsx": "does not read: its supplier writes forget the cached supplier lists",
  "app/migration/page.tsx": "does not read: a Tally import or rollback writes both masters and forgets both lists",
};

const files = walk("app").concat(walk("components"), walk("lib"));
const importers = (needle: RegExp) => files.filter((f) => needle.test(strip(read(f)))).map((f) => f.split(path.sep).join("/"));

test("the request layer and the Supabase client do not import the cache: a read is cached only where its screen asks", () => {
  for (const f of ["lib/api/index.ts", "lib/supabase/client.ts", "lib/supabase/plainRestFetch.ts", "lib/supabase/selectAll.ts"]) {
    assert.ok(!/lib\/cache\/readCache|readCache/.test(strip(read(f))), `${f} imports the read cache, which makes every read cached`);
  }
});

test("only the listed files use the cache", () => {
  const users = importers(/readCache|reportCache|getClientsStale|partyLists/).filter((f) => !f.endsWith(".test.ts"));
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

// ── The customer and supplier lists (POST-A-124, second slice) ──────────────────────────────────────────────────────────────────────

test("the cached customer and supplier lists are read by their own list tabs alone", () => {
  assert.deepEqual(importers(/readCustomerList\b/).filter((f) => f !== "lib/data/partyLists.ts"), ["app/clients/[id]/sales/page.tsx"]);
  assert.deepEqual(importers(/readVendorList\b/).filter((f) => f !== "lib/data/partyLists.ts"), ["app/clients/[id]/purchases/page.tsx"]);
  for (const [page, word] of [["app/clients/[id]/sales/page.tsx", "readCustomerList"], ["app/clients/[id]/purchases/page.tsx", "readVendorList"]] as const) {
    const src = read(page);
    assert.match(src, /readAtText\(paintedFrom\)/, `${page} paints a list without saying when it was read`);
    assert.match(src, /could not be refreshed, so it may not be current/);
    assert.ok(src.includes(word));
  }
});

/** Where a customer or a supplier is written, by RULE: a write method to its API, a write through the typed client, a PostgREST write on
 *  the table (the call chain read up to its statement's end), or the Tally import and its rollback, which write both masters on the server.
 *  Each write must be followed, within its own statement or the next few, by the forget of its family: a write answered with an error may
 *  still have landed (POST-A-414), so the forget comes before the answer is judged. */
const NEAR = 2500;
function writeSites(code: string, fam: "customers" | "vendors"): number[] {
  const res = [
    new RegExp(String.raw`["\`]/api/${fam}/[^"\`]*["\`]\s*,\s*"(POST|PATCH|PUT|DELETE)"`, "g"),
    new RegExp(String.raw`\.from\("${fam}"\)[^;]*?\.(insert|update|upsert|delete)\(`, "g"),
    /\/api\/tally-migration\/jobs\/[^`]*\/(import|rollback)`/g,
  ];
  if (fam === "vendors") res.push(/api\.vendors\.(create|update)\(/g);
  const out: number[] = [];
  for (const re of res) for (const m of code.matchAll(re)) out.push(m.index! + m[0].length);
  return out;
}

test("every write of a customer or a supplier is followed by the forget of that family's cached lists", () => {
  const missing: string[] = [];
  let seen = 0;
  for (const f of files) {
    if (f.split(path.sep).join("/") === "lib/api/index.ts") continue;          // defines the calls, makes none
    const code = strip(read(f));
    for (const [fam, forget] of [["customers", "forgetCustomerLists()"], ["vendors", "forgetVendorLists()"]] as const) {
      for (const at of writeSites(code, fam)) {
        seen += 1;
        if (!code.slice(at, at + NEAR).includes(forget)) missing.push(`${f}: a write of ${fam} at offset ${at} is not followed by ${forget}`);
      }
    }
  }
  assert.ok(seen >= 15, `only ${seen} customer or supplier writes found: the scan has gone blind`);
  assert.deepEqual(missing, []);
});
