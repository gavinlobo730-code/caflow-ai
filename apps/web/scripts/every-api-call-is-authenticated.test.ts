// Every call to the FastAPI backend carries a Bearer token. Run with:
//   node --experimental-strip-types --test scripts/every-api-call-is-authenticated.test.ts
//
// WHY THIS EXISTS
//     apps/api authenticates one way and one way only: core/auth.py reads an
//     `Authorization: Bearer …` header and raises 401 when it is absent. There
//     is no cookie session and no dev fallback once SUPABASE_URL is set. So a
//     `fetch` to an rbac()-guarded route without that header is not a slightly
//     weaker call — it is a call that CANNOT SUCCEED, ever, against a real
//     deployment.
//
//     Eleven of them shipped, and the failure is quiet in the worst way: the
//     401 body is `{"detail": "..."}` with no `success` key, so
//     `if (!j.success) throw new Error(j.error ?? "Failed to load")` shows the
//     word "Failed", or an empty screen, and never the word "Unauthorized".
//
//       * app/clients/[id]/fixed-assets/page.tsx — SEVEN calls, the whole
//         screen. Each sent `credentials: "include"`, which carries a COOKIE
//         this API does not read, so it looked like an auth decision had been
//         made. Every route in routers/fixed_assets.py is
//         Depends(rbac("accounting", …)).
//       * lib/data/tds.ts compute26Q / compute24Q — "Prepare a Return" on
//         /tds/returns (TDS-03). routers/tds.py guards both with
//         rbac("tds","compute").
//       * lib/data/income-tax.ts HRA compute — rbac("income_tax","compute").
//       * lib/api/index.ts documents.parse — rbac("document","write"), so
//         document parsing had never worked.
//
//     A per-file review does not find these: each one looks reasonable beside
//     its neighbours, and only the whole tree read at once shows that eleven
//     calls out of thirty-six were missing the same header.
//
// THE RULE, NOT A SPELLING
//     "No bare fetch" would be a spelling, and a wrong one — app/sign/page.tsx
//     is SUPPOSED to be unauthenticated. The rule is: a call to this backend
//     must carry the token, and the exceptions are the PUBLIC endpoints, named
//     here with the router that makes them public.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const SKIP_DIRS = new Set(["node_modules", ".next", "out", ".vercel", "scripts"]);

// Endpoints that are public BY DESIGN, each with the router that makes it so.
// A path listed here must have NO rbac() guard in apps/api — if one is added,
// the entry becomes a hole rather than an exemption.
const PUBLIC_PATHS: Record<string, string> = {
  "/api/public/engagement-letters":
    "routers/engagement_sign_public.py — a tokenised link the CLIENT opens " +
    "with no login. The 256-bit bearer token in the URL is the credential; " +
    "every query is constrained to that token's row.",
};

/** Anything that proves the call carries the token. */
const CARRIES_TOKEN =
  /Authorization|_authHeaders\(|authHeaders\(|access_token|authedFetch|\brequest[<(]/;

interface Call { file: string; line: number; text: string }

/** Comments blanked, LINE NUMBERS PRESERVED.
 *
 *  Not optional. The note left where each dead call used to be quotes the dead
 *  call verbatim — `fetch(\`${API}/api/fixed-assets/…\`, { credentials:
 *  "include" })` — so a scanner that reads comments fails on the documentation
 *  of its own fix. That is the same trap the backend's direct-write scan hit.
 *
 *  `//` is only treated as a comment when it is not preceded by a colon, so a
 *  `https://` inside a string survives. */
function stripComments(src: string): string {
  const blank = (m: string) => m.replace(/[^\n]/g, " ");
  return src
    .replace(/\/\*[\s\S]*?\*\//g, blank)
    .replace(/(^|[^:])\/\/[^\n]*/g, (_m, pre) => pre + blank(_m.slice(pre.length)));
}

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue;
      sourceFiles(path.join(dir, entry.name), out);
    } else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
      out.push(path.join(dir, entry.name));
    }
  }
  return out;
}

/** Every `fetch(…)` whose argument list mentions this backend, with the WHOLE
 *  call — parenthesis-balanced, so a multi-line options object is inside it and
 *  a header three lines down is not missed. A regex window would be the same
 *  mistake the backend's direct-write scan made with its 400-character cap. */
function apiCalls(): Call[] {
  const found: Call[] = [];
  for (const file of sourceFiles(ROOT)) {
    const src = stripComments(fs.readFileSync(file, "utf8"));
    for (const m of src.matchAll(/\bfetch\(/g)) {
      let depth = 0, j = src.indexOf("(", m.index!);
      for (; j < src.length; j++) {
        if (src[j] === "(") depth++;
        else if (src[j] === ")" && --depth === 0) break;
      }
      const text = src.slice(m.index!, j + 1);
      if (!text.includes("/api/") && !text.includes("API_BASE") && !text.includes("BASE_URL")) continue;
      found.push({
        file: path.relative(ROOT, file),
        line: src.slice(0, m.index!).split("\n").length,
        text,
      });
    }
  }
  return found;
}

const isPublic = (c: Call) => Object.keys(PUBLIC_PATHS).some(p => c.text.includes(p));

test("every fetch to the backend carries a Bearer token", () => {
  const bare = apiCalls().filter(c => !isPublic(c) && !CARRIES_TOKEN.test(c.text));
  assert.deepEqual(
    bare.map(c => `${c.file}:${c.line}`), [],
    "these calls reach an rbac()-guarded API with no Authorization header, so " +
    "they answer 401 against any real deployment:\n  " +
    bare.map(c => `${c.file}:${c.line}  ${c.text.replace(/\s+/g, " ").slice(0, 110)}`).join("\n  ") +
    "\n\nUse `request` from lib/api (or the file's own authed helper), or add " +
    "the path to PUBLIC_PATHS naming the router that makes it public.",
  );
});

test("the scan actually finds the calls it is meant to police", () => {
  // A scanner that silently stops matching keeps passing while checking
  // nothing, which is the main way a guard like this rots. Assert it still
  // sees a real population, and specifically the files the eleven were in.
  const calls = apiCalls();
  assert.ok(calls.length >= 25,
    `only ${calls.length} API fetches found — the scan has stopped matching`);
  for (const f of ["lib/api/index.ts", "lib/data/tds.ts", "lib/data/income-tax.ts"]) {
    assert.ok(calls.some(c => c.file === f), `${f} no longer scanned`);
  }
});

test("credentials: include is never used as if it were authentication", () => {
  // The specific disguise, kept because it is what made seven dead calls read
  // as deliberate. A cookie is not a credential this API knows about, and a
  // call carrying one LOOKS like somebody decided how it authenticates.
  const offenders = apiCalls()
    .filter(c => /credentials:\s*["']include["']/.test(c.text))
    .map(c => `${c.file}:${c.line}`);
  assert.deepEqual(offenders, [],
    "a cookie is not authentication here — core/auth.py reads the " +
    "Authorization header and nothing else:\n  " + offenders.join("\n  "));
});

test("every public exemption says which router makes it public", () => {
  for (const [p, why] of Object.entries(PUBLIC_PATHS)) {
    assert.ok(why.includes(".py"),
      `${p}: name the router that leaves it unguarded, so the exemption can be re-checked`);
    assert.ok(why.length > 40, `${p}: say why it is public, not just that it is`);
  }
});
