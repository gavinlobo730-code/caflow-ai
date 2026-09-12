// BANK-22 — the browser sends a FILE and the account it belongs to, and never
// a parsed statement. Run with:
//   node --experimental-strip-types --test scripts/a-statement-is-parsed-on-the-server-and-belongs-to-an-account.test.ts
//
// WHY THIS EXISTS
//     Two doors created a `bank_statements` row and neither required a bank
//     account. An unlinked statement is one nothing downstream can place: no
//     ledger to post its lines to, no account to reconcile, no column for the
//     register's running balance, and no key for the saved column mapping, so
//     the CA re-maps the same layout every month. Worse, posting did not fail
//     — `bank_posting_service._resolve_bank` fell through to the firm's
//     generic master Bank ledger, which balances perfectly and puts the money
//     in the wrong sub-ledger.
//
//     The second door was `lib/data/bankStatements.ts`, which held a whole
//     browser-side statement parser — its own bank-format detector, its own
//     date reader, its own paise parser — and POSTed the rows it produced to
//     /statements/import. It had no caller and no parameter for a bank
//     account, so it was deleted rather than repaired:
//     `domain/banking/normalizer.py` is the parser, and a file the browser has
//     already turned into rows cannot reach its adapters, the CA's saved
//     mapping, the dedup or the tie-out.
//
// THE RULE, NOT THE SPELLING
//     No screen, and nothing in lib/data, may reach /statements/import — that
//     endpoint takes rows somebody has already parsed, which is work this app
//     does on the server. `lib/api/index.ts` is exempt in both checks below
//     because it is the TRANSPORT: it mirrors the API surface, and the
//     endpoint is a real one for a scripted import. What it must not have is a
//     caller in this app. And every upload FormData must carry
//     bank_account_id.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const SKIP = new Set(["node_modules", ".next", ".git", "out", "dist", "coverage"]);

function sources(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.has(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) sources(p, out);
    else if (/\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(p);
  }
  return out;
}

function code(file: string): string {
  return fs.readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("no screen posts an already-parsed statement", () => {
  const offenders = sources(ROOT)
    .filter(f => !/lib\/api\/index\.ts$/.test(f))      // the transport, not a caller
    .filter(f => /statements\/import|importStatement\s*\(/.test(code(f)));
  assert.deepEqual(offenders.map(f => path.relative(ROOT, f)), [],
    "/statements/import takes rows somebody has already parsed. The browser " +
    "cannot parse a bank statement — domain/banking/normalizer.py has the " +
    "column adapters, the CA's saved mapping, the dedup and the tie-out.");
});

test("the browser holds no bank-statement parser of its own", () => {
  const src = code(path.join(ROOT, "lib/data/bankStatements.ts"));
  assert.doesNotMatch(src, /export function parseCSV|export async function importBankStatement/,
    "deleted with BANK-22 — see the file's own header for why it was deleted " +
    "rather than repaired");
  assert.doesNotMatch(src, /hdfc|icici|axis/i,
    "a bank-format detector in the browser is a second implementation of " +
    "domain/banking/normalizer._ADAPTERS");
});

/** The file split at each function declaration, so the check below is about
 *  the function that uploads and not about the file that contains it — the
 *  same screen also appends bank_account_id when it opens the column mapper,
 *  and a file-level search would be satisfied by that one. */
function functionBodies(src: string): string[] {
  const starts = [...src.matchAll(/^\s*(?:export\s+)?(?:async\s+)?function\s+\w+/gm)]
    .map(m => m.index ?? 0);
  if (!starts.length) return [src];
  return starts.map((from, i) => src.slice(from, starts[i + 1] ?? src.length));
}

test("every statement upload names the account it belongs to", () => {
  const offenders: string[] = [];
  for (const f of sources(ROOT)) {
    if (/lib\/api\/index\.ts$/.test(f)) continue;        // the transport, not a caller
    for (const body of functionBodies(code(f))) {
      if (!/uploadStatement\s*\(|statements\/upload/.test(body)) continue;
      if (!/append\(\s*["']bank_account_id["']/.test(body)) {
        offenders.push(`${path.relative(ROOT, f)}: ${body.trim().split("\n")[0]}`);
      }
    }
  }
  assert.deepEqual(offenders, [],
    "bank_account_id is required on /statements/upload (BANK-22): a statement " +
    "with no account cannot be posted, reconciled or mapped");
});
