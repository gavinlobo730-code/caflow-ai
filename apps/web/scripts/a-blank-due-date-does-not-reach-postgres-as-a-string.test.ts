/**
 * Tasks > New Task: leaving Due Date blank (the field carries no asterisk and no `required`, it is genuinely optional) failed
 * with a raw `invalid input syntax for type date: ""` from Postgres, because `lib/data/tasks.ts` wrote straight to Supabase and
 * sent the form's own default value, an empty string, into a `DATE` column.
 *
 * Since POST-A-227 the task writes go through the API, and the rule is held in two places: the SERVER reads "" as "no date" and
 * refuses a malformed one with a 422 that names the field (`routers/tasks._check_due_date`, tested in
 * apps/api/tests/test_a_task_is_written_through_the_server.py), and this module sends a blank as an explicit null (which the
 * PATCH reads as "clear it", where an absent field means "leave it"). What is asserted here is the half that lives in the
 * browser: that the writes still go through the API, never straight to the table, and that a blank is sent as null.
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
  const start = code.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `could not find ${name} in lib/data/tasks.ts`);
  const open = code.indexOf("{", start);
  let depth = 0, i = open;
  for (; i < code.length; i++) {
    if (code[i] === "{") depth++;
    else if (code[i] === "}") { depth--; if (depth === 0) break; }
  }
  return code.slice(open, i + 1);
}

test("a blank due date does not reach Postgres as a string", async (t) => {
  await t.test("the form's blank due date and blank assignee are sent as an explicit null", () => {
    const body = fnBody("toApiBody");
    assert.match(body, /body\.due_date\s*=\s*input\.due_date\s*\|\|\s*null/,
      "a blank due_date is not turned into null before it is sent");
    assert.match(body, /body\.assigned_to\s*=\s*input\.assignee_id\s*\|\|\s*input\.assigned_to\s*\|\|\s*null/,
      "a blank assignee is not turned into null before it is sent");
  });

  await t.test("a field the caller did not name is not sent (an absent field means leave it)", () => {
    const body = fnBody("toApiBody");
    assert.match(body, /"due_date"\s+in\s+input/, "due_date is sent whether or not the caller named it");
    assert.match(body, /"assignee_id"\s+in\s+input/, "the assignee is sent whether or not the caller named it");
  });

  await t.test("task writes go through the API and never straight to the table", () => {
    for (const fn of ["updateTaskStatus", "deleteTask", "updateTask", "createTask"]) {
      const body = fnBody(fn);
      assert.match(body, /api\.tasks\.(update|delete|create)\(/, `${fn} does not go through the API`);
      assert.ok(!/\.from\(\s*["']tasks["']\s*\)[^;]*\.(insert|update|upsert|delete)\(/s.test(body), `${fn} writes the table directly`);
    }
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /export async function createTask/);
    assert.match(code, /export async function updateTask/);
  });
});
