// POST-A-151, restated for POST-A-010. A non-Partner pressing Delete on a stored document used to see the line vanish while
// the document stayed: Storage answers a denied `remove` with an empty list and no error, and a delete that row security
// hid answers no error and no rows (migrations 261 and 469). The delete is the server's now (DELETE /api/client-documents/{id},
// Partner only), and it refuses with a sentence when no record went; what is left to hold here is the browser's half of the
// same rule: the line leaves the page, and the timeline entry is written, only AFTER the server has said the record is gone.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const WEB = join(import.meta.dirname, "..");

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    if (["node_modules", ".next", "out", "scripts", ".git"].includes(name)) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (/\.tsx?$/.test(name)) yield path;
  }
}

/** Source with comments and string/template literals blanked (same length), so a word inside a message is not code. */
function codeOnly(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => " ".repeat(m.length))
    .replace(/\/\/.*$/gm, (m) => " ".repeat(m.length))
    .replace(/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`/g, (m) => '"' + " ".repeat(Math.max(m.length - 2, 0)) + '"');
}

const CALL = "api.clientDocuments.remove(";

/** The effects that REPORT a deletion: dropping the line, or writing the timeline entry. */
const REPORT = /setDocuments\(|setSharedDocs\(|writeTimelineEvent\(/;

/** The end (exclusive) of the `{ … }` block that opens at or after `from`, or -1. */
function blockEnd(code: string, from: number): number {
  const open = code.indexOf("{", from);
  if (open < 0) return -1;
  let depth = 0;
  for (let k = open; k < code.length; k++) {
    if (code[k] === "{") depth += 1;
    else if (code[k] === "}" && --depth === 0) return k + 1;
  }
  return -1;
}

/**
 * The ONE check the real pages and the negative control both run. `body` starts at the handler's own opening.
 *   1. the server call is made inside a `try`, so a refusal (which `request()` throws as the server's sentence) skips
 *      everything after it;
 *   2. nothing that reports a deletion runs before the call (an optimistic removal);
 *   3. the `catch` that answers a refusal does not itself drop the line or write the timeline entry.
 */
function handlerIsSound(body: string): boolean {
  const code = codeOnly(body);
  const call = code.indexOf(CALL);
  if (call < 0) return false;
  const tryAt = code.lastIndexOf("try {", call);
  if (tryAt < 0 || blockEnd(code, tryAt) <= call) return false;
  if (REPORT.test(code.slice(0, call))) return false;
  const catchAt = code.indexOf("catch", blockEnd(code, tryAt));
  if (catchAt < 0) return false;
  const catchEnd = blockEnd(code, catchAt);
  if (catchEnd < 0 || REPORT.test(code.slice(catchAt, catchEnd))) return false;
  return REPORT.test(code.slice(call, tryAt >= 0 ? blockEnd(code, tryAt) : undefined));
}

test("no screen deletes a client_documents row or a stored file itself: they all go through the server", () => {
  const direct = /from\(\s*["']client_documents["']\s*\)\s*\.delete\(|\.storage\b[\s\S]{0,80}\.remove\(/;
  const offenders: string[] = [];
  let users = 0;
  for (const file of [...walk(join(WEB, "app")), ...walk(join(WEB, "components")), ...walk(join(WEB, "lib"))]) {
    const rel = relative(WEB, file);
    const src = readFileSync(file, "utf8");
    if (direct.test(codeOnly(src))) offenders.push(rel);
    if (src.includes(CALL)) users += 1;
  }
  assert.deepEqual(offenders, [], "delete through api.clientDocuments.remove so a denied delete is not shown as done");
  assert.equal(users, 3, "the three delete handlers (portal documents, vault, client documents) call the server");
});

test("each handler drops the line, and writes the timeline event, only after the server has said the record is gone", () => {
  const handlers: [string, string][] = [
    ["app/client-portal/page.tsx", "async function handleDeleteSharedDoc("],
    ["app/clients/documents/page.tsx", "async function handleDelete("],
    ["app/clients/[id]/documents/page.tsx", "async function handleDeleteDocument("],
  ];
  for (const [rel, start] of handlers) {
    const src = readFileSync(join(WEB, rel), "utf8");
    const from = src.indexOf(start);
    assert.ok(from >= 0, `${rel}: the handler ${start} has moved`);
    const call = src.indexOf(CALL, from);
    assert.ok(call > from, `${rel} does not call the server from ${start}`);
    assert.ok(handlerIsSound(src.slice(from, call + 1600)),
      `${rel}: a line is dropped or a timeline entry written before the server answers, or outside the try, or in the catch`);
  }
  // the timeline entry exists only on the client's documents page, and it waits for the server like the line does
  const page = readFileSync(join(WEB, "app/clients/[id]/documents/page.tsx"), "utf8");
  assert.ok(page.indexOf("writeTimelineEvent(", page.indexOf(CALL)) > 0, "the timeline event has gone");
});

test("negative control: the same check fails an optimistic removal, a removal in the catch, one outside the try, and a word", () => {
  const head = "async function h(doc) {\n";
  const sound = head + `try {\nawait ${CALL}doc.id);\nsetDocuments((p) => p);\n} catch (e) {\ntoast({ title: String(e) });\n}\n}`;
  const optimistic = head + `setDocuments((p) => p);\ntry {\nawait ${CALL}doc.id);\n} catch (e) {\ntoast({ title: String(e) });\n}\n}`;
  const inCatch = head + `try {\nawait ${CALL}doc.id);\n} catch (e) {\nsetDocuments((p) => p);\n}\n}`;
  const noTry = head + `await ${CALL}doc.id);\nsetDocuments((p) => p);\n}`;
  const reportsNothing = head + `try {\nawait ${CALL}doc.id);\n} catch (e) {\ntoast({ title: String(e) });\n}\n}`;
  const wordOnly = head + `try {\nawait ${CALL}doc.id);\n// setDocuments(\n} catch (e) {\ntoast({ title: 'setDocuments( later' });\n}\n}`;
  assert.equal(handlerIsSound(sound), true, "the real shape must pass");
  assert.equal(handlerIsSound(optimistic), false, "an optimistic removal before the call must fail");
  assert.equal(handlerIsSound(inCatch), false, "dropping the line in the catch must fail");
  assert.equal(handlerIsSound(noTry), false, "a call outside a try must fail");
  assert.equal(handlerIsSound(reportsNothing), false, "a handler that never reports the deletion must fail");
  assert.equal(handlerIsSound(wordOnly), false, "the name in a comment or a message is not a report");
});
