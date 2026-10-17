// POST-A-151. A non-Partner pressing Delete on a stored document used to see the line vanish while the document stayed:
// Storage answers a denied `remove` with an empty list and no error, and a delete that row security hid answers no
// error and no rows (migrations 261 and 469). The line now leaves the page only when the server returned the deleted row.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import {
  DOCUMENT_NOT_DELETED, FILE_REMOVED_RECORD_REMAINS, deleteStoredDocument,
  type StoredDocumentClient,
} from "../lib/documents/deleteStoredDocument.ts";

const DOC = { id: "doc-1", file_path: "firm/client/doc-1.pdf" };

function fake(opts: {
  removed?: unknown[] | null; fileError?: string; deleted?: unknown[] | null; rowError?: string;
}): { client: StoredDocumentClient; calls: string[] } {
  const calls: string[] = [];
  const client: StoredDocumentClient = {
    storage: {
      from: (bucket) => ({
        remove: async (paths) => {
          calls.push(`remove:${bucket}:${paths.join(",")}`);
          return { data: "removed" in opts ? opts.removed! : [], error: opts.fileError ? { message: opts.fileError } : null };
        },
      }),
    },
    from: (table) => ({
      delete: () => ({
        eq: (col, val) => ({
          select: async (cols) => {
            calls.push(`delete:${table}:${col}=${val}:${cols}`);
            return { data: "deleted" in opts ? opts.deleted! : [], error: opts.rowError ? { message: opts.rowError } : null };
          },
        }),
      }),
    }),
  };
  return { client, calls };
}

test("a Partner's delete removes the file, asks for the deleted row back, and reports it deleted", async () => {
  const { client, calls } = fake({ removed: [{ name: DOC.file_path }], deleted: [{ id: DOC.id }] });
  assert.deepEqual(await deleteStoredDocument(client, DOC, "Documents"), { deleted: true });
  assert.deepEqual(calls, [
    "remove:Documents:firm/client/doc-1.pdf",
    "delete:client_documents:id=doc-1:id",
  ]);
});

test("a denied delete (empty removal list, no row back, no error) is NOT reported as deleted", async () => {
  const { client } = fake({ removed: [], deleted: [] });
  assert.deepEqual(await deleteStoredDocument(client, DOC, "Documents"), { deleted: false, message: DOCUMENT_NOT_DELETED });
});

test("a record that went while the file was already absent is deleted", async () => {
  const { client } = fake({ removed: [], deleted: [{ id: DOC.id }] });
  assert.deepEqual(await deleteStoredDocument(client, DOC, "Documents"), { deleted: true });
});

test("a file that went while its record stayed says so, and is not reported as deleted", async () => {
  const { client } = fake({ removed: [{ name: DOC.file_path }], deleted: [] });
  assert.deepEqual(await deleteStoredDocument(client, DOC, "Documents"),
    { deleted: false, message: FILE_REMOVED_RECORD_REMAINS });
});

test("a storage error stops before the record is touched, and a row error is passed through", async () => {
  const stopped = fake({ fileError: "bucket unavailable" });
  assert.deepEqual(await deleteStoredDocument(stopped.client, DOC, "Documents"),
    { deleted: false, message: "bucket unavailable" });
  assert.equal(stopped.calls.length, 1, "the record must not be deleted when the file could not be");

  const refused = fake({ removed: [], rowError: "permission denied" });
  assert.deepEqual(await deleteStoredDocument(refused.client, DOC, "Documents"),
    { deleted: false, message: "permission denied" });
});

test("a record the database refuses AFTER the file went says the file is gone, with the reason", async () => {
  // e.g. the original of a versioned document, or one a tax claim cites: a foreign-key refusal once the blob was removed
  const { client } = fake({ removed: [{ name: DOC.file_path }], rowError: "violates foreign key constraint" });
  const out = await deleteStoredDocument(client, DOC, "Documents");
  assert.equal(out.deleted, false);
  assert.ok(!out.deleted && out.message.startsWith(FILE_REMOVED_RECORD_REMAINS), "the screen must say the file is gone");
  assert.ok(!out.deleted && out.message.includes("violates foreign key constraint"), "and keep the reason");
});

test("a null data payload reads as nothing deleted, never as success", async () => {
  const { client } = fake({ removed: null, deleted: null });
  const out = await deleteStoredDocument(client, DOC, "Documents");
  assert.deepEqual(out, { deleted: false, message: DOCUMENT_NOT_DELETED });

  // and a null removal list beside a deleted row is the already-absent file, which is a successful delete
  const absent = fake({ removed: null, deleted: [{ id: DOC.id }] });
  assert.deepEqual(await deleteStoredDocument(absent.client, DOC, "Documents"), { deleted: true });
});

// ── the rule, over the tree ──────────────────────────────────────────────────────────────────────────────────────────

const WEB = join(import.meta.dirname, "..");

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    if (["node_modules", ".next", "out", "scripts", ".git"].includes(name)) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (/\.tsx?$/.test(name)) yield path;
  }
}

test("no screen deletes a client_documents row directly: they all go through the helper", () => {
  const direct = /from\(\s*["']client_documents["']\s*\)\s*\.delete\(/;
  const offenders: string[] = [];
  let helperUsers = 0;
  for (const file of [...walk(join(WEB, "app")), ...walk(join(WEB, "components")), ...walk(join(WEB, "lib"))]) {
    const rel = relative(WEB, file);
    const src = readFileSync(file, "utf8");
    if (rel === join("lib", "documents", "deleteStoredDocument.ts")) continue;
    if (direct.test(src.replace(/\/\/.*$/gm, ""))) offenders.push(rel);
    if (src.includes("deleteStoredDocument(")) helperUsers += 1;
  }
  assert.deepEqual(offenders, [], "delete through lib/documents/deleteStoredDocument so a denied delete is not shown as done");
  assert.equal(helperUsers, 3, "the three delete handlers (portal documents, vault, client documents) use the helper");
});

/** Source with comments and string/template literals blanked (same length), so a word inside a message is not code. */
function codeOnly(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => " ".repeat(m.length))
    .replace(/\/\/.*$/gm, (m) => " ".repeat(m.length))
    .replace(/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`/g, (m) => '"' + " ".repeat(Math.max(m.length - 2, 0)) + '"');
}

/** Where the `if (!out.deleted) …` guard on the helper's answer ENDS, and whether its branch leaves with a return/throw STATEMENT. */
function guardOnTheAnswer(code: string): { end: number; leaves: boolean } | null {
  const head = /if\s*\(\s*!\s*\w+\.deleted\s*\)\s*/.exec(code);
  if (!head) return null;
  const at = head.index + head[0].length;
  if (code[at] !== "{") {
    const stop = code.indexOf(";", at);
    return { end: stop + 1, leaves: /^(?:return|throw)\b/.test(code.slice(at, stop)) };
  }
  let depth = 0;
  for (let k = at; k < code.length; k++) {
    if (code[k] === "{") depth += 1;
    else if (code[k] === "}" && --depth === 0) {
      // a `return`/`throw` that starts a statement directly in the branch (after `{`, `;` or `}`), not one inside a callback
      return { end: k + 1, leaves: /(?:^|[{;}])\s*(?:return|throw)\b/.test(code.slice(at, k).replace(/\([^()]*\)\s*=>\s*\{[^{}]*\}/g, "")) };
    }
  }
  return null;
}

/** The first effect that reports a deletion (drops the line, writes the timeline entry), as an offset, or -1. */
function firstReportOfDeletion(code: string): number {
  return code.search(/setDocuments\(|setSharedDocs\(|writeTimelineEvent\(/);
}

/** The ONE check both the real pages and the negative control run: `body` starts at the handler's own opening. */
function handlerIsSound(body: string, callAt: number): boolean {
  const code = codeOnly(body);
  // nothing that reports a deletion may run before the helper has answered (an optimistic removal)
  const before = firstReportOfDeletion(code.slice(0, callAt));
  if (before !== -1) return false;
  const guard = guardOnTheAnswer(code.slice(callAt));
  if (!guard || !guard.leaves) return false;
  const report = firstReportOfDeletion(code.slice(callAt));
  return report >= guard.end;
}

test("each handler returns before it drops the line, or writes the timeline event, when the delete was not confirmed", () => {
  const handlers: [string, string][] = [
    ["app/client-portal/page.tsx", "async function handleDeleteSharedDoc("],
    ["app/clients/documents/page.tsx", "async function handleDelete("],
    ["app/clients/[id]/documents/page.tsx", "async function handleDeleteDocument("],
  ];
  for (const [rel, start] of handlers) {
    const src = readFileSync(join(WEB, rel), "utf8");
    const from = src.indexOf(start);
    assert.ok(from >= 0, `${rel}: the handler ${start} has moved`);
    const call = src.indexOf("await deleteStoredDocument(", from);
    assert.ok(call > from, `${rel} does not call the helper from ${start}`);
    const body = src.slice(from, call + 1600);
    assert.ok(handlerIsSound(body, call - from),
      `${rel}: a line is dropped or a timeline entry written before the helper answers, or the not-deleted branch does not leave`);
  }
  // the timeline entry exists only on the client's documents page, and it waits for the guard like the line does
  const page = readFileSync(join(WEB, "app/clients/[id]/documents/page.tsx"), "utf8");
  assert.ok(page.indexOf("writeTimelineEvent(", page.indexOf("await deleteStoredDocument(")) > 0, "the timeline event has gone");
});

test("negative control: the same check fails an optimistic removal, a guard that does not leave, and a 'return' that is only a word", () => {
  const head = "async function h(doc) {\n";
  const call = "const out = await deleteStoredDocument(sb, doc, 'Documents');\n";
  const sound = head + call + "if (!out.deleted) { toast({ title: out.message }); return; }\nsetDocuments((p) => p);\n}";
  const optimistic = head + "setDocuments((p) => p);\n" + call + "if (!out.deleted) { return; }\n}";
  const reportsFirst = head + call + "setDocuments((p) => p);\nif (!out.deleted) { return; }\n}";
  const noExit = head + call + "if (!out.deleted) { toast({ title: out.message }); }\nsetDocuments((p) => p);\n}";
  const wordOnly = head + call + "if (!out.deleted) { toast({ title: 'Please return later' }); }\nsetDocuments((p) => p);\n}";
  const callbackReturn = head + call + "if (!out.deleted) { items.forEach((x) => { return x; }); }\nsetDocuments((p) => p);\n}";
  const at = (b: string) => b.indexOf("await deleteStoredDocument(");
  assert.equal(handlerIsSound(sound, at(sound)), true, "the real shape must pass");
  assert.equal(handlerIsSound(optimistic, at(optimistic)), false, "an optimistic removal before the helper call must fail");
  assert.equal(handlerIsSound(reportsFirst, at(reportsFirst)), false, "reporting before the guard must fail");
  assert.equal(handlerIsSound(noExit, at(noExit)), false, "a guard that does not leave must fail");
  assert.equal(handlerIsSound(wordOnly, at(wordOnly)), false, "the word 'return' in a message is not an exit");
  assert.equal(handlerIsSound(callbackReturn, at(callbackReturn)), false, "a return inside a callback is not an exit");
});
