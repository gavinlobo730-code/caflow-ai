// A button that saves or deletes tells the person when it fails (POST-A-515). Run with:
//   node --experimental-strip-types --test scripts/a-button-that-saves-tells-the-person-when-it-fails.test.ts
//
// WHY THIS EXISTS
//     On 19-11-2026 the owner pressed Change Password and the screen said nothing at all, and the owner asked whether other pages do the same. A
//     read-only scan of every function a button, form or dialog is wired to (1,831 of them, 460 waiting on a server call) found places where
//     a failure ended quietly: the four Remove buttons of the GSTR-8 panel and the four of the GSTR-4 annual panel called the delete with no
//     catch, so a refused delete (a locked period) left the row and said nothing; "Detect Matches" dropped the 403 an Executive is answered
//     with (the scan is a Partner's) and changed nothing on a press that found nothing; "Restore version" in the knowledge base kept a
//     comment ("backend enforces") where an answer belonged; the recurring-journal history showed an empty list for a read that failed,
//     which reads as "nothing has run"; the onboarding task's status returned quietly when the server answered `success: false`; and the
//     bank's "Undo" and "Book under" said how many lines moved and not why the rest did not. Each is fixed (see the pins below).
//
// THE RULE (scripts/silentHandlers.ts holds it): a function a person's press runs (an `onClick`, `onSubmit` or `onPress`, on a component
//     or an element) that awaits a server call must not end a failure with no answer on the screen. Four ways to break it are named H1 to
//     H4 there. A quiet catch around a server call that comes AFTER the first one may say why in a comment inside it; the first call, the one
//     the person pressed the button for, may not.
//
// THE LIST (scripts/silent-handlers-baseline.json) holds the places the scan flags that were READ and are quiet on purpose, each with its
//     reason. It only shrinks: a place that is fixed or gone must be deleted from it, and a place that is added is refused.
//
// WHAT THE RULE DOES NOT SEE, said here so it is not mistaken for more: a failed READ that leaves a screen blank (95 catches around a
//     server call that do not tell, most of them prefills, were counted and not read one by one), a callback a component is handed and calls
//     (read where the component stands), a handler reached through something other than a name in the same file, and what a function
//     called `say` or `write` does when it is declared somewhere else.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { countByKey, scanSource, scanTree } from "./silentHandlers.ts";

const WEB = path.join(import.meta.dirname, "..");
const BASELINE = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, "silent-handlers-baseline.json"), "utf8")) as {
  comment: string;
  reviewed: Record<string, { count: number; why: string }>;
};
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");
const flagged = (src: string, rel = "app/x/page.tsx") => scanSource(rel, src).findings.map((f) => `${f.cls}:${f.fn}`);

// ═══ THE TREE ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

test("no function a button runs ends a failure with no answer, except the places read and listed", () => {
  const found = countByKey(scanTree(WEB).findings);
  const added = Object.keys(found).filter((k) => found[k] > (BASELINE.reviewed[k]?.count ?? 0));
  assert.deepEqual(
    added,
    [],
    `A function a person's press runs awaits a server call and can end a failure with no word on the screen: ${added.join("; ")}. Say what ` +
      `happened (a setter, a toast, a callback), or, if it is quiet on purpose, say why in a comment inside the catch.`,
  );
});

test("the list only shrinks: a place that is fixed or gone is deleted from it", () => {
  const found = countByKey(scanTree(WEB).findings);
  const stale = Object.keys(BASELINE.reviewed).filter((k) => (found[k] ?? 0) < BASELINE.reviewed[k].count);
  assert.deepEqual(stale, [], `scripts/silent-handlers-baseline.json lists places the scan no longer finds: ${stale.join("; ")}. Delete them.`);
});

test("every listed place carries the reason it is quiet", () => {
  for (const [key, entry] of Object.entries(BASELINE.reviewed)) {
    assert.ok(entry.why.trim().length >= 40, `${key} is listed without a reason of its own`);
    assert.ok(Number.isInteger(entry.count) && entry.count >= 1, `${key} has no count`);
  }
});

test("the scan reads the whole tree, so an empty answer means none and not nothing scanned", () => {
  const r = scanTree(WEB);
  assert.ok(r.filesScanned > 300, `only ${r.filesScanned} files were scanned`);
  assert.ok(r.handlersWithServerCall > 300, `only ${r.handlersWithServerCall} handlers that await a server call were found`);
});

// ═══ THE RULE'S OWN NEGATIVE CONTROLS ═════════════════════════════════════════════════════════════════════════════════════════════════

test("H4: a server call that throws, outside every try, in a handler a button runs", () => {
  const src = `export default function P() {
    async function save() { setBusy(true); await api.things.save(); }
    return <button onClick={save}>Save</button>;
  }`;
  assert.deepEqual(flagged(src), ["H4:save"]);
});

test("H4 is not raised when the call is inside a try, or handed to a same-file function that catches and says it", () => {
  const tried = `export default function P() {
    async function save() { try { await api.things.save(); } catch (e) { setError(String(e)); } }
    return <button onClick={save}>Save</button>;
  }`;
  const wrapped = `export default function P() {
    async function write(action) { try { await action(); } catch (e) { setSaid({ text: String(e) }); } }
    const save = () => write(async () => { await api.things.save(); });
    return <button onClick={save}>Save</button>;
  }`;
  const awaitedWrapper = `export default function P() {
    async function act(fn) { try { await fn(); } catch (e) { setError(String(e)); } }
    async function suspend() { await act(() => api.things.suspend()); }
    return <button onClick={suspend}>Suspend</button>;
  }`;
  assert.deepEqual(flagged(tried), []);
  assert.deepEqual(flagged(wrapped), []);
  assert.deepEqual(flagged(awaitedWrapper), []);
});

test("a local function that merely happens to be called in the handler does not carry the failure of an unrelated call", () => {
  // the shape of the eight Remove buttons: `loadRows` has its own catch, for ITS read, and says nothing of the delete before it
  const src = `export default function P() {
    async function loadRows() { try { await api.rows.list(); } catch (e) { setRowsError(String(e)); } }
    async function remove(id) { setBusy(true); await api.rows.delete(id); await loadRows(); }
    return <button onClick={() => remove(1)}>Remove</button>;
  }`;
  assert.deepEqual(flagged(src), ["H4:remove"]);
});

test("H2: a catch that drops the failure of the first server call is flagged even when a comment says it is fine", () => {
  const empty = `export default function P() {
    async function restore() { setBusy(true); try { await api.kb.restore(); } catch { } }
    return <button onClick={restore}>Restore</button>;
  }`;
  const commented = `export default function P() {
    async function restore() { setBusy(true); try { await api.kb.restore(); } catch { /* backend enforces */ } }
    return <button onClick={restore}>Restore</button>;
  }`;
  assert.deepEqual(flagged(empty), ["H2:restore"]);
  assert.deepEqual(flagged(commented), ["H2:restore"]);
});

test("H2: a later call may be quiet on purpose when its catch says why, and may not when it does not", () => {
  const explained = `export default function P() {
    async function save() {
      try { await api.things.save(); } catch (e) { setError(String(e)); return; }
      try { await api.timeline.write(); } catch { /* the timeline write must not block the save */ }
    }
    return <button onClick={save}>Save</button>;
  }`;
  const unexplained = explained.replace("/* the timeline write must not block the save */", "");
  assert.deepEqual(flagged(explained), []);
  assert.deepEqual(flagged(unexplained), ["H2:save"]);
});

test("H2 is not raised for a catch that records the failure for the caller, or logs it and says it", () => {
  const collects = `export default function P() {
    async function importAll(rows) {
      const failures = [];
      for (const r of rows) { try { await api.rows.add(r); } catch (e) { failures.push(String(e)); } }
      setFailures(failures);
    }
    return <button onClick={() => importAll([])}>Import</button>;
  }`;
  const logsAndSays = `export default function P() {
    async function save() { setBusy(true); try { await api.things.save(); } catch (e) { console.error(e); setError("Not saved."); } }
    return <button onClick={save}>Save</button>;
  }`;
  assert.deepEqual(flagged(collects), []);
  assert.deepEqual(flagged(logsAndSays), []);
  const logsOnly = logsAndSays.replace(' setError("Not saved.");', "");
  assert.deepEqual(flagged(logsOnly), ["H2:save"]);
});

test("H3: a failure branch that returns with no value and no word", () => {
  const silent = `export default function P() {
    async function update(id) {
      try {
        const json = await api.tasks.update(id);
        if (!json.success) return;
        setDone(true);
      } catch (e) { setError(String(e)); }
    }
    return <button onClick={() => update(1)}>Done</button>;
  }`;
  const says = silent.replace("if (!json.success) return;", "if (!json.success) { setError(json.error); return; }");
  const hands = silent.replace("if (!json.success) return;", "if (!json.success) return { ok: false, error: json.error };");
  assert.deepEqual(flagged(silent), ["H3:update"]);
  assert.deepEqual(flagged(says), []);
  assert.deepEqual(flagged(hands), []);
});

test("a callback handed to a component is read where the component stands, but a press on a component is judged", () => {
  const callback = `export default function P() {
    async function save(data) { await api.things.save(data); }
    return <Modal onSave={save} />;
  }`;
  const press = `export default function P() {
    async function save() { setBusy(true); await api.things.save(); }
    return <Button onClick={save}>Save</Button>;
  }`;
  assert.deepEqual(flagged(callback), []);
  assert.deepEqual(flagged(press), ["H4:save"]);
});

test("two components in one file may each declare a handleSave, and a button means the one in its own component", () => {
  const src = `function Dialog() {
    async function handleSave() { try { await api.things.save(); } catch (e) { setError(String(e)); } }
    return <button onClick={handleSave}>Save</button>;
  }
  export default function Page() {
    async function handleSave(data) { setBusy(true); await api.things.upsert(data); }
    return <Dialog onSave={handleSave} />;
  }`;
  assert.deepEqual(flagged(src), []);
});

// ═══ THE FIXED PLACES STAY FIXED ═══════════════════════════════════════════════════════════════════════════════════════════════════════

test("the GSTR-8 and GSTR-4 panels remove a row through one helper that catches, checks the answer and says it", () => {
  for (const rel of ["components/gst/Gstr8Panel.tsx", "components/gst/Gstr4AnnualPanel.tsx"]) {
    const src = read(rel);
    assert.match(src, /const removeRow = useCallback\(async \(remove: \(\) => Promise<\{ success: boolean; error\?: string \| null \}>\) => \{/, rel);
    assert.match(src, /if \(!res\.success\) \{\s*setRemoveError\(res\.error \?\? "Couldn't remove that row\."\);/, rel);
    assert.match(src, /setRemoveError\(failureSentence\(e, "Couldn't remove that row\.", "write"\)\);/, rel);
    assert.match(src, /\{removeError && <Callout tone="problem" title="That row was not removed">\{removeError\}<\/Callout>\}/, rel);
    assert.equal((src.match(/removeRow\(\(\) => api\./g) ?? []).length, 4, `${rel}: every Remove goes through the helper`);
    assert.doesNotMatch(src, /await api\.(ecommerceOperator|gstr4Annual)\.delete\w+\(/, `${rel}: no Remove awaits a delete on its own`);
  }
});

test("restoring a knowledge-base version says a refusal and asks for the version once", () => {
  const src = read("app/knowledge/page.tsx");
  assert.match(src, /const res = \(await api\.knowledge\.restoreVersion\(id, version\)\) as \{ success\?: boolean; error\?: string \| null \} \| null;\s*if \(res && res\.success === false\) \{\s*setError\(res\.error \?\? "Couldn't restore that version\."\);/);
  assert.doesNotMatch(src, /catch \{ \/\* backend enforces \*\/ \}/);
  assert.equal((src.match(/restoreVersion\(/g) ?? []).length, 1);
});

test("the recurring-journal history says when it could not be read, and an empty one is only the empty one", () => {
  const src = read("app/accounting/recurring/page.tsx");
  assert.match(src, /else setHistoryError\(res\.error \?\? "Couldn't read this template's history\."\);/);
  assert.match(src, /setHistoryError\(e instanceof Error \? e\.message : "Couldn't read this template's history\."\);/);
  assert.ok((src.match(/[hH]istoryError/g) ?? []).length >= 6, "the state is declared, cleared, set twice and shown");
});

test("the onboarding task's refusal is said, not dropped", () => {
  const src = read("app/clients/[id]/lifecycle/page.tsx");
  assert.match(src, /if \(!json\.success\) \{[^}]*setError\(json\.error \?\? "Couldn't update the task\."\);\s*return;\s*\}/);
});

test("Detect Matches says a refusal, and says what it found", () => {
  const src = read("app/clients/[id]/relationships/page.tsx");
  assert.match(src, /if \(!res\?\.success\) \{ setError\(res\?\.error \?\? "Matches could not be looked for just now\."\); return; \}/);
  assert.match(src, /new_matches_detected/);
  assert.match(src, /No new cross-client matches found\./);
  assert.match(src, /\{detectNote && <Callout tone="note">\{detectNote\}<\/Callout>\}/);
  assert.doesNotMatch(src, /catch \{ \/\* non-fatal — the list simply does not change \*\/ \}/);
});

test("the bank's Undo and Book under say how many lines stayed and the first reason", () => {
  const src = read("components/banking/EntriesTab.tsx");
  assert.match(src, /\$\{refused\.length\} could not be undone: \$\{refused\[0\]\}/);
  assert.match(src, /\$\{refused\.length\} could not be booked: \$\{refused\[0\]\}/);
  assert.doesNotMatch(src, /catch \{ \/\* counted \*\/ \}/);
  assert.doesNotMatch(src, /catch \{ \/\* reported by the count \*\/ \}/);
});
