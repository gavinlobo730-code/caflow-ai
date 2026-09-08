// Marking a GST return filed goes through the API, so the period lock engages.
// Run with:
//   node --experimental-strip-types --test scripts/a-filed-gst-return-locks-its-period.test.ts
//
// WHY THIS EXISTS
//     journal_period_lock_reason (migrations 266 and 267) reads
//     `public.filings` to decide whether a filed return freezes the period
//     behind it — the guard that stops a CA editing a journal inside a period
//     already declared to the department (CGST Act §37(3), §39(9)).
//
//     Exactly one thing writes that table: `record_filing`
//     (apps/api/services/gst_filing_record_service.py), called from
//     routers/gst_workspace.py when a return's status moves to "submitted".
//
//     lib/data/gst.ts's markGSTR3BFiled and markGSTR1Filed did not call it.
//     They wrote `status: "submitted"` straight into gstr3b_returns /
//     gstr1_returns over PostgREST, so:
//
//       * record_filing never ran, `public.filings` stayed empty, and the
//         lock — correct SQL, tested against seeded rows — could never fire on
//         anything a CA actually did. Production bore it out: one
//         gstr3b_returns row at ca_approved, no ARN, and `filings` empty.
//       * rbac() never ran either. It does not run on ANY PostgREST call; the
//         only check there is RLS. So any role that could open the GST screen
//         could mark a return filed, where the route requires Manager+ and an
//         explicit ca_approved.
//       * submitted_at, ca_approved_by and the ARN-on-`filings` half were
//         written by hand or not at all.
//
//     This is the same family as the deleted browser-side filing demo (see
//     one-filing-demo-and-the-kill-switch-reaches-it.test.ts): a write that
//     looks like it worked, taking a shortcut past the server that owns the
//     rule.
//
// WHAT THIS DOES NOT DO
//     It reads source, not behaviour — it cannot prove the backend writes the
//     filings row, which is the Python suite's job
//     (apps/api/tests, gst_filing_record_service). What it pins is that the
//     browser asks the server instead of writing the table itself, which is
//     the half that regressed.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const GST_DATA = "lib/data/gst.ts";
const API_CLIENT = "lib/api/index.ts";

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

/** Everything between a function's `{` and its matching `}`, comments
 *  stripped — the assertions are about CODE, and the notes left behind quote
 *  the very writes they replaced. */
function body(src: string, fnName: string): string {
  const start = src.indexOf(`export async function ${fnName}(`);
  assert.notEqual(start, -1, `${fnName} is gone — has it been renamed?`);
  const open = src.indexOf("{", src.indexOf(")", start));
  let depth = 0;
  let i = open;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) break;
  }
  return src
    .slice(open, i + 1)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(e.name) && !p.includes(`${path.sep}scripts${path.sep}`)) out.push(p);
  }
  return out;
}

const MARKERS = ["markGSTR3BFiled", "markGSTR1Filed"] as const;

// ── the browser no longer writes the return row itself ──────────────────────

for (const fn of MARKERS) {
  test(`${fn} does not write the returns table over PostgREST`, () => {
    const b = body(read(GST_DATA), fn);
    for (const write of [".update(", ".upsert(", ".insert(", ".delete("]) {
      assert.equal(
        b.includes(write), false,
        `${fn} still does a PostgREST ${write} — rbac() does not run on that ` +
        `call and record_filing never fires, so public.filings stays empty ` +
        `and the period lock cannot engage.`,
      );
    }
  });
}

test("markGSTR3BFiled PATCHes the backend GSTR-3B status route", () => {
  const b = body(read(GST_DATA), "markGSTR3BFiled");
  assert.match(b, /api\.gstWorkspace\.setGstr3bStatus\(/);
  assert.match(b, /status:\s*"submitted"/);
});

test("markGSTR1Filed PATCHes the backend GSTR-1 status route", () => {
  const b = body(read(GST_DATA), "markGSTR1Filed");
  assert.match(b, /api\.gstWorkspace\.setGstr1Status\(/);
  assert.match(b, /status:\s*"submitted"/);
});

for (const fn of MARKERS) {
  test(`${fn} sends the CA's explicit confirmation`, () => {
    // routers/gst_workspace.py refuses "submitted" outright without it:
    // "Explicit ca_approved=true required ... CA must confirm." A call that
    // omits it is refused every time, which is a broken button, not a safe one.
    assert.match(body(read(GST_DATA), fn), /ca_approved:\s*true/);
  });

  test(`${fn} treats a refused request as a failure`, () => {
    // The GST workspace router answers a refusal — wrong role, no CA
    // confirmation, return not found — as HTTP 200 with
    // { success: false, error }. request() only throws on !res.ok, so an
    // unchecked call would set the screen to "Filed" for a filing the server
    // declined to record.
    const b = body(read(GST_DATA), fn);
    assert.match(
      b, /!\s*res\.success/,
      `${fn} does not check the { success, error } envelope`,
    );
  });
}

// ── the API client actually names the backend routes ───────────────────────

test("the API client exposes the GST status routes at the paths the backend serves", () => {
  const src = read(API_CLIENT);
  // routers/gst_workspace.py: APIRouter(prefix="/api/gst-workspace") with
  // @router.patch("/gstr1/{return_id}/status") and the gstr3b twin.
  assert.match(src, /setGstr1Status:/);
  assert.match(src, /setGstr3bStatus:/);
  assert.match(src, /`\/api\/gst-workspace\/gstr1\/\$\{[^}]+\}\/status`/);
  assert.match(src, /`\/api\/gst-workspace\/gstr3b\/\$\{[^}]+\}\/status`/);
  // PATCH, not POST or PUT — the route is only mounted for PATCH.
  const gstBlock = src.slice(src.indexOf("gstWorkspace: {"));
  const statusCalls = gstBlock.slice(0, gstBlock.indexOf("\n  },"));
  assert.equal(
    (statusCalls.match(/method:\s*"PATCH"/g) ?? []).length, 2,
    "both status calls must be PATCH",
  );
});

// ── and nothing anywhere else takes the shortcut ───────────────────────────

test("no screen marks a GST return submitted over PostgREST", () => {
  // The pattern, not the instance: a `.from("gstr1_returns"| "gstr3b_returns")`
  // chain that WRITES and mentions submitted is the bug this file exists for,
  // wherever it turns up next.
  const offenders: string[] = [];
  for (const file of walk(WEB)) {
    const src = fs.readFileSync(file, "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    const re = /\.from\(\s*"(gstr1_returns|gstr3b_returns)"\s*\)/g;
    let hit: RegExpExecArray | null;
    while ((hit = re.exec(src)) !== null) {
      const chain = src.slice(hit.index, hit.index + 700);
      const writes = /\.(update|upsert|insert|delete)\(/.test(chain);
      if (writes && /submitted/.test(chain)) {
        offenders.push(`${path.relative(WEB, file)} (${hit[1]})`);
      }
    }
  }
  assert.deepEqual(
    offenders, [],
    "a GST return is being marked submitted straight into the table — " +
    "public.filings never gets its row and the period lock never engages",
  );
});
