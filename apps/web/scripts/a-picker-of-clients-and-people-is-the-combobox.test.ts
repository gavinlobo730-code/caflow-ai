// A picker that chooses one of the practice's clients, team members, entities or tasks is the
// shared searchable lookup, never a native <select>. Run with:
//   node --experimental-strip-types --test scripts/a-picker-of-clients-and-people-is-the-combobox.test.ts
//
// WHAT WAS WRONG (POST-A-155). The combobox migration of 1 July 2026 converted the pickers it
// listed and left the rest "low priority": the task form's client and assignee, a task's blocking
// picker, the template instantiation's client, the two TDS section lists, the relationship
// entity picker and the reassign-to-member picker stayed native, so a firm with a hundred clients
// scrolled a flat list that cannot be searched.
//
// THE RULE, not a list of spellings: a `<select>` whose options are mapped from a list of the
// firm's own records (clients, team members, entities, tasks, TDS sections) fails. A short fixed
// vocabulary (priority, status, period, minor head) stays native on purpose, and so do the
// name-based state selects of Settings and onboarding, which persist a state NAME and not a code.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== "node_modules") walk(rel, out); }
    else if (e.name.endsWith(".tsx")) out.push(rel);
  }
  return out;
}

const RECORDS = /\{\s*(?:clients|teamMembers|members|entities|candidates|choices\.(?:deductible|challan))\s*\.map\(/;

export function nativePickersOfRecords(src: string): number {
  return [...src.matchAll(/<select\b[\s\S]*?<\/select>/g)].filter((m) => RECORDS.test(m[0])).length;
}

test("the detector finds a native select over the firm's records and nothing else", () => {
  assert.equal(nativePickersOfRecords(`<select>{clients.map(c => <option key={c.id}>{c.name}</option>)}</select>`), 1);
  assert.equal(nativePickersOfRecords(`<select>{choices.deductible.map(k => <option key={k}>{k}</option>)}</select>`), 1);
  assert.equal(nativePickersOfRecords(`<select><option value="a">A</option><option value="b">B</option></select>`), 0);
  assert.equal(nativePickersOfRecords(`<EntityLookup items={clients.map(c => c)} />`), 0);
});

test("no screen picks a client, a team member, an entity, a task or a TDS section with a native select", () => {
  const offenders: string[] = [];
  let scanned = 0;
  for (const f of [...walk("app"), ...walk("components")]) {
    scanned++;
    const n = nativePickersOfRecords(stripComments(fs.readFileSync(path.join(WEB, f), "utf8")));
    if (n) offenders.push(`${f}: ${n}`);
  }
  assert.ok(scanned > 300, "the tree was not read");
  assert.deepEqual(offenders, [], "use components/lookups (ClientLookup, EntityLookup) for a list of the firm's records");
});
