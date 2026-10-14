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
// THE SAME FAMILY, TWO MORE MEMBERS (POST-A-223, POST-A-224)
//     * APPROVAL. approveGSTR1 / approveGSTR3B wrote `status: "ca_approved"` and
//       `ca_approved_by: <an id the page supplied>` straight into the table. The
//       route requires Manager and above, the table's policy asks Executive, and
//       the id was the Supabase AUTH id for a column that is a foreign key to the
//       INTERNAL user id. They go through the status route now, like the filing.
//     * REBUILD. saveGSTR1Return / saveGSTR3BReturn upserted `status: "draft"`
//       over whatever the row held, so every Build or Compute click on a FILED
//       return turned it back into an unfiled draft with a CA Approve button,
//       its ARN and approver still on the row. They refuse a submitted return
//       now (the server's save and recompute do) and void an approval, which is
//       what the server's recompute does. This guard's old rule looked for
//       `submitted` and `filed` values only, so a reset to `draft` and an
//       approval both walked past it.
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

// ── approval goes through the API too (POST-A-223) ─────────────────────────

const APPROVERS = [
  ["approveGSTR3B", "setGstr3bStatus"],
  ["approveGSTR1", "setGstr1Status"],
] as const;

for (const [fn, route] of APPROVERS) {
  test(`${fn} does not write the returns table over PostgREST`, () => {
    const b = body(read(GST_DATA), fn);
    for (const write of [".update(", ".upsert(", ".insert(", ".delete("]) {
      assert.equal(
        b.includes(write), false,
        `${fn} writes the return itself: rbac() does not run on a PostgREST call, ` +
        "so an Executive could approve a return the route reserves to a Manager, " +
        "and the approver is whatever id the page supplies.",
      );
    }
  });

  test(`${fn} asks the status route, with the CA's confirmation, and checks the answer`, () => {
    const b = body(read(GST_DATA), fn);
    assert.match(b, new RegExp(`api\\.gstWorkspace\\.${route}\\(`));
    assert.match(b, /status:\s*"ca_approved"/);
    assert.match(b, /ca_approved:\s*true/);
    assert.match(b, /!\s*res\.success/, `${fn} does not check the { success, error } envelope`);
  });

  test(`${fn} takes no approver from the caller`, () => {
    // The server derives the approver from the signed-in user (a users.id). A
    // parameter named for one is the browser choosing who approved.
    const src = read(GST_DATA);
    const start = src.indexOf(`export async function ${fn}(`);
    const signature = src.slice(start, src.indexOf("{", src.indexOf(")", start)));
    assert.doesNotMatch(signature, /userId|approver|approvedBy/i,
      `${fn} accepts an approver from its caller`);
  });
}

// ── a rebuild does not undo a filing or leave a stale approval (POST-A-224) ─

const SAVERS = [
  ["saveGSTR3BReturn", "GSTR-3B"],
  ["saveGSTR1Return", "GSTR-1"],
] as const;

for (const [fn, label] of SAVERS) {
  test(`${fn} refuses a return that has been filed`, () => {
    const b = body(read(GST_DATA), fn);
    // The existing row is looked up with its status...
    assert.match(b, /\.select\(\s*"id,\s*status"\s*\)/,
      `${fn} no longer reads the existing return's status before overwriting it`);
    // ...and a submitted one stops the write, in the server's own words.
    assert.match(b, /existing\?\.status\s*===\s*"submitted"/);
    assert.match(b, new RegExp(`${label} for .* has already been filed and cannot be changed`),
      `${fn} lost the refusal of a filed return`);
    assert.ok(b.indexOf('"submitted"') < b.indexOf(".upsert("),
      `${fn} checks for a filed return AFTER it writes`);
  });

  test(`${fn} says why when row security refuses a rebuild of an approved return`, () => {
    // Migration 491: an Executive may not change a return a Manager has approved. The raw message is a policy
    // name, which tells the CA nothing about what to do next.
    const b = body(read(GST_DATA), fn);
    assert.match(b, /row-level security/);
    assert.match(b, new RegExp(`${label} for .* has been approved, so only someone who may approve`));
  });

  test(`${fn} voids an earlier approval when it rewrites the figures`, () => {
    const b = body(read(GST_DATA), fn);
    assert.match(b, /ca_approved_by:\s*null/);
    assert.match(b, /ca_approved_at:\s*null/);
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

const FILING_STATE_TABLES = ["gstr1_returns", "gstr3b_returns", "compliance_calendar", "mca_filings"] as const;
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
  // mca_filings (POST-A-225): its filed state is `status: "filed"` with an `srn`.
  if (/\bstatus:\s*"filed"/.test(chain)) return true;
  for (const m of chain.matchAll(/(?:filed_date|arn_number|srn)\s*:\s*([^,\n}]*)/g)) {
    const value = m[1].trim();
    if (value && value !== "null" && value !== "undefined") return true;
  }
  return false;
}

// Screens that still record a filing state themselves, with the reason. This list may only SHRINK, and it is EMPTY:
// the two entries that stood here were the ITR screen's single and bulk "mark filed" (POST-A-226), which now go
// through the same API door as the GST tracker. Named in the test rather than excluded by a narrower regex, because
// a narrower regex is how this table was missed in the first place.
const STILL_WRITING_IT_THEMSELVES: string[] = [];

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

/** Does this chain SET an approval, as opposed to clearing one? Voiding an
 *  approval on a rebuild (`ca_approved_by: null`) is correct and must not trip. */
function setsAnApproval(chain: string): boolean {
  if (/status:\s*"ca_approved"/.test(chain)) return true;
  for (const m of chain.matchAll(/ca_approved_(?:by|at)\s*:\s*([^,\n}]*)/g)) {
    const value = m[1].trim();
    if (value && value !== "null" && value !== "undefined") return true;
  }
  return false;
}

test("no screen approves a GST return straight into the table", () => {
  const offenders: string[] = [];
  for (const file of walk(WEB)) {
    const src = fs.readFileSync(file, "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    const re = /\.from\(\s*"(gstr1_returns|gstr3b_returns)"\s*\)/g;
    let hit: RegExpExecArray | null;
    while ((hit = re.exec(src)) !== null) {
      const chain = statementAt(src, hit.index);
      if (/\.(update|upsert|insert|delete)\(/.test(chain) && setsAnApproval(chain)) {
        offenders.push(`${path.relative(WEB, file)} (${hit[1]})`);
      }
    }
  }
  assert.deepEqual(
    offenders, [],
    "a GST return is being approved straight into the table: rbac() does not run " +
    "there, the approver is supplied by the browser, and the route's own refusals " +
    "(Manager and above, the explicit confirmation, books that have moved) never fire",
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

test("the ITR screen marks a filing through the API, singly and in bulk (POST-A-226)", () => {
  const src = read("app/income-tax/page.tsx")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  assert.equal(
    (src.match(/api\.compliance\.markFiled\(/g) ?? []).length, 2,
    "both the single and the bulk mark-filed on the ITR screen must go through the API",
  );
  assert.ok(
    (src.match(/!res\.success/g) ?? []).length >= 2,
    "a refused mark-filed must not read as success: the route answers a refusal as HTTP 200 with { success: false }",
  );
  assert.doesNotMatch(src, /filing_status:\s*"filed"/);
});

test("the MCA screen records a filing as filed through the API, in all three places (POST-A-225)", () => {
  // Creating a filed row, marking one filed, marking a batch filed: each used to write `status: "filed"`, the SRN
  // and a date straight into mca_filings, so an Executive could record a statutory filing as done, the route's
  // Manager-and-above rule and the CA's confirmation never ran, and the add modal supplied TODAY as the date.
  const src = read("app/mca/page.tsx")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  assert.equal((src.match(/api\.mca\.setFilingStatus\(/g) ?? []).length, 3);
  assert.ok((src.match(/res\.success/g) ?? []).length >= 3,
    "the answer's envelope must be read: the route answers a refusal as HTTP 200 with { success: false }");
  assert.equal((src.match(/ca_approved:\s*true/g) ?? []).length, 3);
  assert.doesNotMatch(src, /filed_date:\s*status\s*===\s*"Filed"\s*\?\s*todayLocalISO/,
    "the add modal must not stamp today's date as the date a filing was made");
});

test("the API client names the MCA status route the backend serves, as a PATCH (POST-A-225)", () => {
  const src = read(API_CLIENT);
  assert.match(src, /setFilingStatus:/);
  assert.match(src, /`\/api\/mca-workspace\/filings\/\$\{[^}]+\}\/status`/);
  const block = src.slice(src.indexOf("setFilingStatus:"));
  assert.match(block.slice(0, 700), /method:\s*"PATCH"/);
});
