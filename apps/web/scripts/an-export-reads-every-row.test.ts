/**
 * An export reads every row, or the file goes out silently short.
 *
 * THE DEFECT
 *
 *   PostgREST caps a response at ~1000 rows (`db-max-rows`) and reports
 *   nothing when it does — no error, no flag, no short-read signal. Three
 *   screens built a download straight from an unpaged `.from(...)`:
 *
 *     app/risks                     compliance_calendar (x3), dsc_records,
 *                                   loans, fixed_deposits
 *     app/accounting/receivables    fee_invoices, clients
 *     app/accounting/coa-export     chart_of_accounts
 *
 *   `compliance_calendar` carries one row per obligation per client per
 *   period, so a 50-client book passes 1000 inside a single year — about
 *   1,450 rows for twelve GSTR-1, twelve GSTR-3B, four TDS statements and an
 *   ITR each. `fee_invoices` passes 1000 in under two years at the same size.
 *   The CSV opened, looked complete, and was short by however much the cap
 *   had removed.
 *
 * WHY THE RULE IS ABOUT EXPORTS AND NOT EVERY READ
 *
 *   71 of the 102 files touching PostgREST still have at least one read that
 *   is neither paged nor bounded by a .range/.limit/.single — counted with
 *   comments stripped, so prose about a query is not mistaken for one. Most
 *   are bounded in PRACTICE: one client, one month, one document. And a SCREEN
 *   that truncates is at least a screen somebody is looking at, with scroll
 *   and filters to suggest there is more.
 *
 *   An export is different in kind: the row set IS the answer, one CSV line
 *   per record, and the file leaves the building with nothing to say rows are
 *   missing. A CA foots it. So the rule held here is narrow and defensible —
 *   a read that feeds a download pages — rather than a budget over 98 files,
 *   which is the shape that gets raised until it means nothing. The other 68
 *   files are recorded as a finding, not silently blessed.
 *
 * A SECOND RULE, FROM THE TRIAGE OF 18-10-2026 (POST-A-135)
 *
 *   A scan of every `.from(...).select(...)` in app, components and lib with no `.limit`,
 *   `.range`, `.single`, `.maybeSingle`, `count`, `id` lookup or pager found 82 reads in 54 files.
 *   Most are what the paragraph above says: one client, one party, one document. Six were not, and
 *   each FEEDS A FIGURE on a screen that has other reads, which is why they cannot go on the list of
 *   screens that must page everything they read:
 *
 *     app/gst            compliance_calendar  GSTR-1/3B/9 rows of every client and every year, ordered
 *                                              OLDEST FIRST: a cut at 1000 dropped the newest filings,
 *                                              which the counts above the table are about
 *     app/income-tax     compliance_calendar  the ITR rows, same shape
 *     app/payroll/attendance
 *                        attendance           one row per employee per month for a YEAR, summed into
 *                                              "leaves used": ninety employees pass 1000, and the
 *                                              balance left came out too high
 *                        leave_balances       one per employee per year
 *     app/tds            tds_deductions       a client's whole register, summed into every tab total
 *
 *   `PAGED_READS_THAT_FEED_A_FIGURE` names each (screen, table) and the test below asks the SOURCE:
 *   every read of that table on that screen goes through a pager and carries `.order("id")`. The
 *   remaining ~76 reads are recorded in POST-A-135 as bounded by their scope or as plain lists.
 *
 * ONE SCREEN IS LISTED FOR A DIFFERENT REASON, AND SAYING WHICH IS THE POINT
 *
 *   `app/accounting/recurring` also has an Export button, but it builds its
 *   CSV from `templates`, which comes from the API. Its PostgREST read feeds
 *   the account DROPDOWNS. It is paged for the same silent-truncation reason
 *   and it is NOT an export read, so it is listed apart — a guard that lumped
 *   it in would be asserting something false about the screen in order to
 *   keep one list.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const WEB = join(import.meta.dirname, "..");
const PAGER = "lib/supabase/selectAll.ts";
const SKIP = new Set(["node_modules", ".next", "out", ".vercel", ".git"]);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

/** Comments are stripped first: a rule stated about SOURCE must not be
 *  satisfied — or broken — by prose describing it. That mistake has been made
 *  in this repository before. */
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

/** The source of the loop whose header starts at `from`, found by brace depth.
 *  Returns null for a loop with no braced body (a one-liner cannot hold a page
 *  walk) or an unbalanced one. */
function loopBody(src: string, from: number): string | null {
  const open = src.indexOf("{", from);
  if (open === -1) return null;
  // A `{` past the end of the header belongs to some later statement.
  if (/\n\s*\n/.test(src.slice(from, open))) return null;
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") {
      depth--;
      if (depth === 0) return src.slice(open, i + 1);
    }
  }
  return null;
}

/** The screens whose download is built from a PostgREST read, each listed with
 *  the tables it must page — so a read added to one of them without paging it
 *  fails here rather than in a CA's spreadsheet. */
const EXPORT_SCREENS: Record<string, string[]> = {
  // `app/risks/page.tsx` LEFT this list on 24-09-2026, and the property it was
  // here for did not: the screen used to read compliance_calendar, dsc_records,
  // loans and fixed_deposits itself, and its Export CSV was built from what
  // came back. The whole register now comes from GET /api/risks/register, so
  // the browser reads no table at all — and the four reads are paged in
  // `apps/api/services/risk_register_service.py`, which
  // `test_the_risk_register_is_derived_in_one_place.py::
  // test_the_service_pages_every_read` holds to exactly this rule, counting
  // `db.table(...)` calls against `fetch_all` calls.
  //
  // An entry removed because its subject MOVED is not an entry softened. The
  // difference is that the new home is named here and asserted there.
  "app/accounting/receivables/page.tsx": ["fee_invoices", "clients"],
  "app/accounting/coa-export/page.tsx": ["chart_of_accounts"],
};

/** Paged for the same reason, but the read feeds a control rather than a file.
 *  Kept separate so neither claim has to be softened to cover both. */
const PAGED_NOT_EXPORTS: Record<string, string[]> = {
  "app/accounting/recurring/page.tsx": ["chart_of_accounts"],
};

const ALL_PAGED = { ...EXPORT_SCREENS, ...PAGED_NOT_EXPORTS };

test("every PostgREST read on these screens goes through the one pager", () => {
  for (const [rel, tables] of Object.entries(ALL_PAGED)) {
    const src = code(readFileSync(join(WEB, rel), "utf8"));

    assert.ok(
      /from\s+["']@\/lib\/supabase\/selectAll["']/.test(src),
      `${rel} reads PostgREST but does not import selectAll`,
    );

    // Counting rather than parsing: a read added outside the pager raises the
    // .from() count without raising the selectAll() count.
    const froms = src.match(/\.from\(\s*["'][a-z_0-9]+["']/g) ?? [];
    const pagers = src.match(/selectAll\s*[<(]/g) ?? [];
    assert.ok(
      pagers.length >= froms.length,
      `${rel} has ${froms.length} PostgREST reads but only ${pagers.length} ` +
        `selectAll calls — a read is unpaged and will be silently short past ` +
        `~1000 rows`,
    );

    for (const t of tables) {
      assert.ok(
        new RegExp(`\\.from\\(\\s*["']${t}["']`).test(src),
        `${rel} no longer reads ${t} — update the list above and say why`,
      );
    }
  }
});

test("a paged read is totally ordered, so pages cannot shift under it", () => {
  // selectAll pages by OFFSET. Postgres gives no ordering guarantee without an
  // ORDER BY, and a NON-UNIQUE one (invoice_date, account_name, client_name)
  // leaves ties free to land either side of a page boundary — so a row can be
  // returned twice, or never. The fix is a unique tiebreaker last: `.order("id")`.
  // It need not be in the projection, so no exported column changes.
  for (const rel of Object.keys(ALL_PAGED)) {
    const src = code(readFileSync(join(WEB, rel), "utf8"));
    const pagers = (src.match(/selectAll\s*[<(]/g) ?? []).length;
    const tiebreaks = (src.match(/\.order\(\s*["']id["']\s*\)/g) ?? []).length;
    assert.ok(
      tiebreaks >= pagers,
      `${rel}: ${pagers} paged reads but only ${tiebreaks} \`.order("id")\` ` +
        `tiebreakers — an OFFSET-paged read without a unique total ordering ` +
        `can duplicate or drop rows at a page boundary`,
    );
  }
});

test("there is ONE browser pager, not a copy per screen", () => {
  // The backend's own note: eleven modules carry a private _paginate_all copy
  // and "adding a twelfth is the thing not to do". The browser has exactly one
  // module, exporting selectAll (OFFSET waves) and selectAllKeyset (cursor).
  //
  // STATED BY CONTAINMENT, because neither cheaper spelling works. Matching on
  // the NAME collides with homonyms — lib/table/useDataTable.ts exports
  // `selectAllFiltered`, which ticks every filtered checkbox and pages nothing.
  // Matching a `.range(` near any loop collides the other way — lib/data/tasks.ts
  // pages by a CALLER-supplied offset, one page per call, with an unrelated
  // `for` elsewhere in the file. Both spellings were tried and both fired on
  // code that was correct.
  //
  // What actually distinguishes a hand-rolled pager is that the SAME code
  // decides the offset and loops over it: a `.range(` or a cursor `.limit(`
  // INSIDE a loop body. So the body is found by brace depth and searched.
  const offenders: string[] = [];
  for (const f of walk(WEB)) {
    const rel = relative(WEB, f);
    if (rel === PAGER || rel.startsWith("scripts/")) continue;
    const src = code(readFileSync(f, "utf8"));
    for (const m of src.matchAll(/\b(while|for)\s*\(/g)) {
      const body = loopBody(src, m.index!);
      if (body && /\.range\(|\.limit\(/.test(body)) {
        offenders.push(`${rel} loops over a paging call`);
        break;
      }
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `a second full-table pager was added — use ${PAGER} instead:\n  ${offenders.join("\n  ")}`,
  );
});

test("BOTH pagers stop on a short page, never on a count", () => {
  const src = code(readFileSync(join(WEB, PAGER), "utf8"));
  // PostgREST's count can be unreliable alongside an embedded relation, so
  // trusting it would reintroduce exactly the silent truncation this prevents.
  //
  // COUNTED, not merely matched: the module exports TWO pagers — selectAll
  // (OFFSET waves) and selectAllKeyset (cursor) — and a negative control that
  // broke the first still passed, because the second's copy of the line kept
  // the pattern present. A guard that cannot tell which function it is looking
  // at is asserting that the FILE contains a string, not that either pager is
  // correct.
  const stops = (src.match(/rows\.length < pageSize/g) ?? []).length;
  assert.equal(
    stops,
    2,
    `expected both selectAll and selectAllKeyset to stop on a short page; ` +
      `found ${stops} such checks — a pager now stops on a row count, which is ` +
      `precisely the unreliable signal this helper exists to avoid`,
  );
  // Each page asks for exactly pageSize rows, so a full page means "the limit
  // we asked for". If db-max-rows were ever lowered BELOW pageSize the first
  // page would come back short, read as end-of-data, and truncate silently.
  // Counted for the same reason, and the same negative control proved it:
  // both signatures default pageSize, so asserting the string merely existed
  // stayed green with one of them raised to 5000.
  const sizes = (src.match(/pageSize = 1000/g) ?? []).length;
  assert.equal(
    sizes,
    2,
    `expected both pagers to default pageSize to 1000; found ${sizes}. A page ` +
      `size ABOVE the server's db-max-rows makes the first page come back ` +
      `short, read as end-of-data, and truncate silently — this bug wearing ` +
      `its own fix as a disguise.`,
  );
});

// ── Reads that feed a figure on a screen that makes other reads (POST-A-135) ────────────────────────

/** The (screen, table) pairs whose reads feed a count, a total or a balance. A screen here may make any number of OTHER
 *  reads (singles, writes, lookups); only the named table's reads are held to the pager. */
const PAGED_READS_THAT_FEED_A_FIGURE: Record<string, string[]> = {
  "app/gst/page.tsx": ["compliance_calendar"],
  "app/income-tax/page.tsx": ["compliance_calendar"],
  "app/payroll/attendance/page.tsx": ["attendance", "leave_balances"],
  "app/tds/page.tsx": ["tds_deductions"],
};

interface Read { paged: boolean; ordered: boolean }

/** Every READ of `table` in `src` (a chain that selects and neither inserts, updates, deletes nor upserts), and whether it is
 *  wrapped in a pager and carries a unique `.order("id")`. The chain is the statement from `.from(` to the `;` at depth 0. */
function readsOf(src: string, table: string): Read[] {
  const out: Read[] = [];
  const header = new RegExp(`\\.from\\(\\s*["']${table}["']\\s*\\)`, "g");
  for (const m of src.matchAll(header)) {
    const start = m.index!;
    let depth = 0;
    let end = start;
    while (end < src.length && end - start < 1600) {
      const c = src[end];
      if (c === "(" || c === "[" || c === "{") depth++;
      else if (c === ")" || c === "]" || c === "}") {
        depth--;
        if (depth < 0) break;
      } else if (c === ";" && depth <= 0) break;
      end++;
    }
    const chain = src.slice(start, end);
    if (/\.(insert|update|delete|upsert)\(/.test(chain) || !/\.select\(/.test(chain)) continue;
    const back = src.slice(Math.max(0, start - 300), start);
    out.push({
      paged: /selectAll(?:Keyset)?\s*(?:<[^>]*>)?\s*\(\s*\(\)\s*=>\s*[\w$.]*\s*$/.test(back),
      ordered: /\.order\(\s*["']id["']\s*\)/.test(chain),
    });
  }
  return out;
}

test("every read that feeds a figure goes through a pager and has a unique ordering", () => {
  let reads = 0;
  for (const [rel, tables] of Object.entries(PAGED_READS_THAT_FEED_A_FIGURE)) {
    const src = code(readFileSync(join(WEB, rel), "utf8"));
    assert.ok(/from\s+["']@\/lib\/supabase\/selectAll["']/.test(src), `${rel} does not import the pager`);
    for (const t of tables) {
      const found = readsOf(src, t);
      assert.ok(found.length > 0, `${rel} no longer reads ${t}: update PAGED_READS_THAT_FEED_A_FIGURE and say why`);
      reads += found.length;
      for (const r of found) {
        assert.ok(r.paged, `${rel}: a read of ${t} feeds a figure and is not wrapped in selectAll/selectAllKeyset, so it is cut at ~1000 rows without a word`);
        assert.ok(r.ordered, `${rel}: a paged read of ${t} has no .order("id") tiebreaker, so a row can be returned twice or never at a page boundary`);
      }
    }
  }
  assert.ok(reads >= 7, `only ${reads} reads were examined: the scan has stopped seeing them`);
});

test("the scan tells a paged read from an unpaged one and ignores a write (negative controls)", () => {
  // The controls are BUILT, not written out: `test_direct_write_tables_are_role_guarded.py` scans every .ts file under apps/web for
  // a from-call chain that reaches an insert, and a literal write against a payroll table in this file would be read as the
  // browser writing that table (it was, on the first run). For the same reason no literal from-call with a name in quotes
  // appears in this file's comments: `test_frontend_tables_exist.py` and the RLS matrix's table list read those too.
  const from = (t: string) => `.from(${JSON.stringify(t)})`;
  const paged = `const { data } = await selectAll(() => sb\n  ${from("attendance")}\n  .select("*")\n  .eq("year", y)\n  .order("id"));`;
  const unpaged = `const { data } = await sb\n  ${from("attendance")}\n  .select("*")\n  .eq("year", y);`;
  const noTiebreak = `const { data } = await selectAll(() => sb${from("attendance")}.select("*").order("month"));`;
  const write = `await sb${from("attendance")}.insert({ year: 1 });`;
  assert.deepEqual(readsOf(paged, "attendance"), [{ paged: true, ordered: true }]);
  assert.deepEqual(readsOf(unpaged, "attendance"), [{ paged: false, ordered: false }]);
  assert.deepEqual(readsOf(noTiebreak, "attendance"), [{ paged: true, ordered: false }]);
  assert.deepEqual(readsOf(write, "attendance"), []);
  assert.deepEqual(readsOf(paged, "tds_deductions"), []);
});
