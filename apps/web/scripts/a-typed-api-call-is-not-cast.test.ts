// A cast over a TYPED api namespace is an assertion the compiler would
// otherwise check — and this repository has the receipts.
//
// `api.clients.list()` was declared `request("/api/clients")`, so its return
// type was `{}` and every caller cast it. Five callers, TWO different beliefs
// about the shape of one endpoint:
//
//   app/team/assignments  as ApiResp<{ clients: Client[] }>   ✅ right
//   app/payroll/page      as ApiResp<{ clients: Client[] }>   ✅ right
//   app/settings/multi-currency  as { data?: ClientRow[] }    ❌ wrong
//   app/payroll/people    as Promise<ApiResp<Client[]>>       ❌ wrong
//
// The endpoint answers `{clients, total}`. So multi-currency handed an OBJECT
// to `arrayOrEmpty`, which answered `[]` exactly as it should, and the screen
// listed no clients for any firm, permanently; and payroll/people put the
// whole envelope into a `Client[]` state, so the next `clients.find(...)`
// threw "clients.find is not a function". Both followed the payload rule in
// CLAUDE.md — they just applied it to the wrong FIELD, which is precisely the
// thing a type can check and a convention cannot.
//
// Typing the namespace found both in one tsc run. This guard keeps the casts
// from coming back on the namespaces that have since been typed, so the
// compiler stays the only authority on their shape.
//
// ⚠️ THIS IS DELIBERATELY NOT A BLANKET RULE. 131 casts over `api.*` calls
// exist today and most sit over namespaces still declared `request(...)` with
// no type argument, where the cast is the only shape information there is.
// Banning all 131 at once produces a budget somebody raises until it means
// nothing. The ratchet is per namespace: TYPE one, then add it here and its
// casts have to go.
//
// Run with: node --experimental-strip-types --test scripts/a-typed-api-call-is-not-cast.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const SKIP = new Set(["node_modules", ".next", "out", ".vercel"]);

/** Namespace calls whose return type `lib/api/index.ts` declares. Grow this
 *  list as namespaces get typed; never shrink it to make a cast pass. */
const TYPED_CALLS = ["api.clients.list("];

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (SKIP.has(e.name)) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name) && !e.name.includes(".test.")) out.push(p);
    }
  };
  for (const folder of ["app", "components", "lib"]) walk(path.join(WEB, folder));
  return out;
}

test("the typed calls really are typed in lib/api", () => {
  // Without this the list below could name a call that is still `{}`, and the
  // guard would be forbidding the only shape information those callers have.
  const api = fs.readFileSync(path.join(WEB, "lib/api/index.ts"), "utf8");
  for (const call of TYPED_CALLS) {
    const member = call.replace("api.", "").replace(/\.\w+\($/, "");
    assert.ok(api.includes(member), `lib/api has no ${member} namespace`);
  }
  assert.match(api, /list: \(\) => request<ApiResp<\{ clients: ClientSummary\[\]; total: number \}>>/,
    "api.clients.list() is no longer typed — either re-type it, or take it out " +
    "of TYPED_CALLS along with the reason");
});

test("no caller casts a typed api call", () => {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    const src = stripComments(fs.readFileSync(file, "utf8"));
    for (const call of TYPED_CALLS) {
      let i = src.indexOf(call);
      while (i !== -1) {
        // Look at what follows the closing paren of this call, on the same line.
        const lineEnd = src.indexOf("\n", i);
        const tail = src.slice(i + call.length, lineEnd === -1 ? undefined : lineEnd);
        if (/\)\s*as\s/.test(tail)) {
          offenders.push(`${path.relative(WEB, file)}: ${call}…) as …`);
        }
        i = src.indexOf(call, i + 1);
      }
    }
  }
  assert.deepEqual(
    offenders,
    [],
    "these callers cast a call whose type lib/api already declares:\n  " +
      offenders.join("\n  ") +
      "\n\nDelete the cast and let tsc check it. A cast over a typed call " +
      "asserts a shape instead of checking one — which is how two screens came " +
      "to hold two different beliefs about GET /api/clients."
  );
});

test("this guard is looking at the real tree", () => {
  const files = sourceFiles();
  assert.ok(files.length > 300, `only ${files.length} source files found`);
  const callers = files.filter((f) =>
    stripComments(fs.readFileSync(f, "utf8")).includes("api.clients.list("));
  assert.ok(callers.length >= 4,
    `only ${callers.length} callers of api.clients.list() — the scan has stopped matching`);
});
