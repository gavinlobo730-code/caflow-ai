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

/** The PostgREST statement that starts at `from`, up to its terminating `;`.
 *
 *  A fixed-size window instead of a real boundary reads whatever happens to
 *  follow, and what follows the add-filing insert is the API call that FIXES
 *  the defect — `markFiled(id, { filed_date: filedDate })` — so a
 *  700-character window reported the fix as the bug. The chain is capped as
 *  well, so a file with no semicolon after the call cannot swallow the rest of
 *  itself. */
function statementAt(src: string, from: number): string {
  const end = src.indexOf(";", from);
  return src.slice(from, end === -1 ? from + 700 : Math.min(end, from + 2000));
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
      const chain = statementAt(src, hit.index);
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


// ── the tracker, which was the other half and was not swept for ────────────
//
// GST-14. The sweep above names two tables, and `compliance_calendar` is a
// third: /gst wrote filing_status / filed_date / arn_number into it over
// PostgREST, single-row and bulk, with no rbac(), no record_filing and so no
// `public.filings` row — the same defect in a table the guard written for that
// defect did not look at. A guard that names a SPELLING misses the next one;
// this asks the rule instead: nothing in the browser sets a filing state on
// any table itself.

const FILING_STATE_TABLES = ["gstr1_returns", "gstr3b_returns", "compliance_calendar"] as const;
/** Does this chain SET a filed state, as opposed to merely naming the columns?
 *
 *  Creating a row with `filing_status: "pending", filed_date: null` is the
 *  correct shape and must not trip — the add-filing modal does exactly that
 *  and then records the filing through the API. Written as a function rather
 *  than one regex because the regex form of "not null" is a trap: in
 *  `/filed_date:\s*(?!null)/` the `\s*` backtracks to zero characters and the
 *  lookahead then compares against " null", which is not "null", so it matches
 *  every time — a guard that fires on the very shape it is meant to allow. */
function setsAFiledState(chain: string): boolean {
  if (/status:\s*"submitted"/.test(chain)) return true;
  if (/filing_status:\s*"filed"/.test(chain)) return true;
  for (const m of chain.matchAll(/(?:filed_date|arn_number)\s*:\s*([^,\n}]*)/g)) {
    const value = m[1].trim();
    if (value && value !== "null" && value !== "undefined") return true;
  }
  return false;
}

// Screens that still record a filing state themselves, with the reason. This
// list may only SHRINK. Both entries are income-tax obligations: an ITR or an
// advance-tax instalment is not a GST period, so no `public.filings` row is
// due for them and the period lock is not the thing at stake — but rbac()
// still does not run on those writes, which is its own finding and its own
// module. Named here rather than excluded by a narrower regex, because a
// narrower regex is how this table was missed in the first place.
const STILL_WRITING_IT_THEMSELVES = [
  "app/income-tax/page.tsx (compliance_calendar)",
  "app/income-tax/page.tsx (compliance_calendar)",
];

test("no screen writes a filing state straight into a table", () => {
  const offenders: string[] = [];
  for (const file of walk(WEB)) {
    const src = fs.readFileSync(file, "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    const re = new RegExp(`\\.from\\(\\s*"(${FILING_STATE_TABLES.join("|")})"\\s*\\)`, "g");
    let hit: RegExpExecArray | null;
    while ((hit = re.exec(src)) !== null) {
      const chain = statementAt(src, hit.index);
      if (/\.(update|upsert|insert|delete)\(/.test(chain) && setsAFiledState(chain)) {
        offenders.push(`${path.relative(WEB, file)} (${hit[1]})`);
      }
    }
  }
  assert.deepEqual(
    offenders, STILL_WRITING_IT_THEMSELVES,
    "a filing is being recorded straight into a table — rbac() does not run " +
    "there, record_filing never fires, public.filings stays empty and the " +
    "period lock cannot engage. If you have FIXED one, delete its entry from " +
    "STILL_WRITING_IT_THEMSELVES; the list may only shrink.",
  );
});

test("the add-filing modal does not create a row already marked filed", () => {
  // A third path to the same defect, on the same screen: "Add GST Filing" let
  // a CA create a calendar row with filing_status "filed" in the INSERT, so a
  // back-dated filing entered that way locked nothing either.
  const src = read("app/gst/page.tsx");
  assert.doesNotMatch(
    src, /filing_status:\s*filedDate\s*\?/,
    "the row must be created pending and the filing recorded through the API",
  );
});

test("the tracker marks a filing through the API", () => {
  const src = read("app/gst/page.tsx");
  // THREE paths on this one screen, and all three had the defect: the
  // single-row modal, the bulk modal (the worst — marking twelve months filed
  // left twelve periods open), and "Add GST Filing", which could create a row
  // already marked filed.
  assert.equal(
    (src.match(/api\.compliance\.markFiled\(/g) ?? []).length, 3,
    "every mark-filed path on the tracker must go through the API",
  );
  // ...and both check the envelope. The backend answers a refusal as HTTP 200
  // with { success: false }, so an unchecked call shows "Filed" for a request
  // the server declined.
  assert.ok(
    (src.match(/!res\.success|!marked\.success/g) ?? []).length >= 3,
    "a refused mark-filed must not read as success",
  );
});

test("the API client names the compliance mark-filed route the backend serves", () => {
  const src = read(API_CLIENT);
  assert.match(src, /markFiled:/);
  assert.match(src, /`\/api\/compliance\/calendar\/\$\{[^}]+\}\/filed`/);
  const block = src.slice(src.indexOf("markFiled:"));
  assert.match(block.slice(0, 400), /method:\s*"PATCH"/);
});
