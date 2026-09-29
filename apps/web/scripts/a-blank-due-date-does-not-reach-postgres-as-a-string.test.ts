/**
 * Tasks > New Task: leaving Due Date blank (the field carries no asterisk and
 * no `required` — it is genuinely optional, same as every other optional
 * date field in this product) failed with a raw
 * `invalid input syntax for type date: ""` from Postgres, because
 * `lib/data/tasks.ts::createTask` writes straight to Supabase — there is no
 * FastAPI request model standing in front of this table (CLAUDE.md's "The
 * frontend's second data path") — and sent the form's own default value, an
 * empty string, into a `DATE` column.
 *
 * The established pattern for an optional date on this exact write path is
 * `field || null` (OpeningBalancesTab.tsx, income-tax/notices/page.tsx); this
 * file's own createTask already applies the identical shape to
 * assignee_id/assigned_to for the same reason (an empty UUID is 22P02, an
 * empty date is 22P02 too) — due_date now gets the same treatment rather
 * than a UUID-specific fix that misses the date column beside it.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const FILE = path.join(WEB, "lib/data/tasks.ts");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(FILE, "utf8");
const code = withoutComments(raw);

function fnBody(name: string): string {
  const start = code.indexOf(`export async function ${name}(`);
  assert.notEqual(start, -1, `could not find ${name} in lib/data/tasks.ts`);
  // Balance braces from the function's own opening one.
  const open = code.indexOf("{", start);
  let depth = 0, i = open;
  for (; i < code.length; i++) {
    if (code[i] === "{") depth++;
    else if (code[i] === "}") { depth--; if (depth === 0) break; }
  }
  return code.slice(open, i + 1);
}

test("a blank due date does not reach Postgres as a string", async (t) => {
  await t.test("createTask normalises a blank due_date to null before insert()", () => {
    const body = fnBody("createTask");
    // Destructured out of `rest` — the same treatment assignee_id/assigned_to
    // already get, so it is never sent unconditionally as whatever the form
    // typed (including "").
    assert.match(body, /\{\s*assignee_id,\s*assigned_to,\s*due_date,\s*\.\.\.rest\s*\}\s*=\s*input/,
      "due_date is not pulled out of the spread the way assignee_id/assigned_to are");
    assert.match(body, /due_date:\s*due_date\s*\|\|\s*null/,
      "createTask's insert() does not normalise an empty due_date to null");
    // The exact old shape — the bare field landing straight in `...rest` — is
    // what raised 22P02; asserting the destructure above is not enough on its
    // own if a stray `due_date` key sneaks back in some other way.
    assert.ok(!/\.\.\.rest,\s*\n?\s*\.\.\.\(assignee_id/.test(body) || body.includes("due_date: due_date || null"),
      "rest still carries an unguarded due_date");
  });

  await t.test("updateTask normalises an explicitly-cleared due_date to null", () => {
    const body = fnBody("updateTask");
    assert.match(body, /due_date.*in input.*&&.*!input\.due_date/s,
      "updateTask does not detect a cleared (falsy) due_date");
    assert.match(body, /patch\.due_date\s*=\s*null/,
      "updateTask does not normalise a cleared due_date to null");
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /export async function createTask/);
    assert.match(code, /export async function updateTask/);
  });
});
