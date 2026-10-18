// POST-A-247. Four screens deleted a row over PostgREST and read nothing back (a document request, a shared report, an
// income-tax notice, a scheduled report). The delete policies on those tables are role-aware (migration 261), so for a
// Reviewer the delete is hidden by row security and answers no error and no rows: the line left the page, or a toast said
// "Schedule deleted", for a row that was still there. The line now leaves the page only when the server returned the row.
// The sibling for stored documents is a-document-delete-says-when-nothing-was-deleted.test.ts (POST-A-151).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { ROW_NOT_DELETED, deleteRowAndConfirm, type RowDeleteClient } from "../lib/data/deleteRowAndConfirm.ts";
import { stripComments } from "./stripComments.ts";

function fake(answer: { data: unknown[] | null; error: { message: string } | null }) {
  const calls: string[] = [];
  const client: RowDeleteClient = {
    from: (table) => ({
      delete: () => ({
        eq: (col, val) => ({
          select: async (cols) => {
            calls.push(`delete:${table}:${col}=${val}:${cols}`);
            return answer;
          },
        }),
      }),
    }),
  };
  return { client, calls };
}

test("a delete the server confirms by returning the row is reported deleted, and the row is asked for back", async () => {
  const { client, calls } = fake({ data: [{ id: "r-1" }], error: null });
  assert.deepEqual(await deleteRowAndConfirm(client, "document_requests", "r-1"), { deleted: true });
  assert.deepEqual(calls, ["delete:document_requests:id=r-1:id"]);
});

test("a delete row security hid (no error, no rows) is NOT reported as deleted", async () => {
  const { client } = fake({ data: [], error: null });
  assert.deepEqual(await deleteRowAndConfirm(client, "scheduled_reports", "s-1"), { deleted: false, message: ROW_NOT_DELETED });
});

test("a null payload reads as nothing deleted, never as success", async () => {
  const { client } = fake({ data: null, error: null });
  assert.deepEqual(await deleteRowAndConfirm(client, "it_notices", "n-1"), { deleted: false, message: ROW_NOT_DELETED });
});

test("a database error is passed through in its own words", async () => {
  const { client } = fake({ data: null, error: { message: "violates foreign key constraint" } });
  assert.deepEqual(await deleteRowAndConfirm(client, "shared_reports", "x"), { deleted: false, message: "violates foreign key constraint" });
});

// ── the rule, over the tree ──────────────────────────────────────────────────────────────────────────────────────────

const WEB = join(import.meta.dirname, "..");

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    if (["node_modules", ".next", "out", "scripts", ".git"].includes(name)) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (/\.tsx?$/.test(name) && !/\.test\./.test(name)) yield path;
  }
}

/** Every `.delete()` whose statement never asks for the row back: the result is either dropped or only its error is read. */
function unreadDeletes(src: string): number {
  const code = stripComments(src);
  let n = 0;
  for (const m of code.matchAll(/\.delete\(\)/g)) {
    const end = code.indexOf(";", m.index);
    const statement = code.slice(m.index, end < 0 ? undefined : end);
    if (!/\.select\(/.test(statement)) n += 1;
  }
  return n;
}

/** Deletes that are not fixed here, with why. A named list that can only shrink: a new unread delete fails, and a fixed one
 *  must have its entry deleted (equality in both directions). */
const NOT_FIXED_HERE: Record<string, number> = {
  // POST-A-227 moves the task delete behind the API, which is the real fix and removes the call.
  "lib/data/tasks.ts": 1,
};

test("no browser delete drops its result, apart from the one named", () => {
  const found: Record<string, number> = {};
  for (const root of ["app", "components", "lib"]) {
    for (const file of walk(join(WEB, root))) {
      const n = unreadDeletes(readFileSync(file, "utf8"));
      if (n > 0) found[relative(WEB, file).replace(/\\/g, "/")] = n;
    }
  }
  assert.deepEqual(found, NOT_FIXED_HERE,
    "delete through lib/data/deleteRowAndConfirm so a hidden delete is not shown as done (or add the file with a reason)");
});

test("the four screens go through the helper", () => {
  for (const [rel, table] of [
    ["app/client-portal/page.tsx", "document_requests"],
    ["app/client-portal/page.tsx", "shared_reports"],
    ["app/income-tax/notices/page.tsx", "it_notices"],
    ["app/settings/scheduled-reports/page.tsx", "scheduled_reports"],
  ] as const) {
    const code = stripComments(readFileSync(join(WEB, rel), "utf8"));
    assert.ok(new RegExp(`deleteRowAndConfirm\\(getSupabaseClient\\(\\),\\s*"${table}"`).test(code), `${rel} does not delete ${table} through the helper`);
  }
});

test("each handler returns before it drops the line, or reloads, when the delete was not confirmed", () => {
  for (const [rel, start] of [
    ["app/client-portal/page.tsx", "async function handleDeleteRequest("],
    ["app/income-tax/notices/page.tsx", "async function deleteNotice("],
  ] as const) {
    const src = readFileSync(join(WEB, rel), "utf8");
    const from = src.indexOf(start);
    assert.ok(from >= 0, `${rel}: ${start} has moved`);
    const body = stripComments(src.slice(from, from + 700));
    const call = body.indexOf("deleteRowAndConfirm(");
    const guard = body.indexOf("if (!out.deleted)");
    const report = body.search(/setDocRequests\(|loadData\(\)/);
    assert.ok(call >= 0 && guard > call, `${rel}: the answer is not checked right after the call`);
    assert.ok(/if \(!out\.deleted\)\s*\{[\s\S]{0,200}?\breturn;/.test(body.slice(guard)), `${rel}: the not-deleted branch does not leave`);
    assert.ok(report > guard, `${rel}: the line is dropped or the list reloaded before the answer is checked`);
  }
});

test("negative control: the scan fails a delete that reads nothing, and one that reads only the error", () => {
  // The sources are assembled from parts: the table-name guards in apps/api read every client call that names a table
  // by a literal under apps/web, and a fixture that spelled one out would be reported as a query on a table that does
  // not exist.
  const from = (name: string) => `.${"from"}("${name}")`;
  assert.equal(unreadDeletes(`await sb${from("t")}.delete().eq("id", id);`), 1);
  assert.equal(unreadDeletes(`const { error } = await sb${from("t")}.delete().eq("id", id);\nif (error) throw error;`), 1);
  assert.equal(unreadDeletes(`const r = await sb${from("t")}.delete().eq("id", id).select("id");`), 0);
  assert.equal(unreadDeletes(`// await sb${from("t")}.delete().eq("id", id);`), 0);
});

// POST-A-255. The employee's declaration save deletes the saved lines and inserts the new ones. The delete's result was
// not read, so a refusal let the insert run and the declared amounts sat twice. It is read now: its error stops the save,
// and an answer of no rows for a declaration whose lines were loaded stops it too (row security hides a refused delete
// without an error), and a failed read of the lines is a failed load rather than an empty form.
test("the declaration save reads its delete and does not show empty boxes for lines it could not read", () => {
  const code = stripComments(readFileSync(join(WEB, "components/portal/TaxDeclarationTab.tsx"), "utf8"));
  assert.match(code, /\.delete\(\)\s*\.eq\("declaration_id", saved\.id\)\s*\.select\("id"\)/);
  assert.match(code, /if \(delErr\) throw delErr;/);
  assert.match(code, /savedLineCount\.current > 0 && \(removed \?\? \[\]\)\.length === 0/);
  assert.match(code, /if \(rowsErr\) throw rowsErr;/);
});
