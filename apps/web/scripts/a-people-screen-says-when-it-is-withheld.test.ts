// POST-A-542 (the role walk of 21-11-2026): a People screen says in words when the person may not read it, the Team screen
// offers Invite only to somebody who can invite, and a list that could not be read is not an empty one.
//   node --experimental-strip-types --test scripts/a-people-screen-says-when-it-is-withheld.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { PRACTICE_PEOPLE_SECTIONS } from "../lib/workspace/practiceWorkspace.ts";
import { mayOpen, screenRule } from "../lib/access/screenAccess.ts";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(import.meta.dirname, "..");
const code = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

test("every People screen is opened by its own pair in the one table, and by nothing else", () => {
  // The RULE, over the one list of People screens. These screens had a gate of their own (`PeopleAccessGate`, in a layout
  // above each) from POST-A-542 until the one gate around every firm page asked the same pairs (POST-A-543); the older gate
  // was removed under POST-A-545. What must stay true is that a screen added to the list is in the table with ITS pair.
  for (const s of PRACTICE_PEOPLE_SECTIONS) {
    const parts = s.href.split("/").filter(Boolean);
    assert.ok(fs.existsSync(path.join(WEB, "app", ...parts, "page.tsx")), `${s.href} has no page`);
    assert.deepEqual(screenRule(s.href), { all: [s.requires] }, `${s.href} is not opened by ${s.requires.join(" ")} in the one table`);
    const holdsIt = { can: (r: string, a: string) => (r === s.requires[0] && a === s.requires[1]) || (r === "team" && a === "read"), isPartner: false };
    const holdsNothing = { can: () => false, isPartner: false };
    assert.equal(mayOpen(s.href, holdsIt).allowed, true, `${s.href} is refused to somebody who holds its pair`);
    const refused = mayOpen(s.href, holdsNothing);
    assert.equal(refused.allowed, false, `${s.href} opens for somebody who holds nothing`);
    assert.ok(refused.ask, `${s.href} is refused with nothing to ask for`);
  }
});

test("the one gate is what answers, it waits until the permissions are known, and the older gate is gone", () => {
  const gate = code("components/auth/ScreenAccessGate.tsx");
  assert.match(gate, /if \(!answer \|\| answer\.allowed \|\| answer\.partnerOnly \|\| !answer\.ask\) return <>\{children\}<\/>;/);
  assert.doesNotMatch(gate, /userRole|"Partner"|"Manager"/, "the gate asks a role where it should ask the permission the server asks");
  assert.match(gate, /that is not the same as there being nothing/);
  assert.match(code("components/AppShell.tsx"), /<ScreenAccessGate pathname=\{realPathname\}>\{children\}<\/ScreenAccessGate>/);
  for (const gone of ["components/team/PeopleAccessGate.tsx", "app/team/layout.tsx", "app/approvals/layout.tsx"]) {
    assert.equal(fs.existsSync(path.join(WEB, gone)), false, `${gone} is back: two gates on one screen are two answers`);
  }
});

test("the Team screen offers Invite Member only to somebody who can invite", () => {
  const page = code("app/team/page.tsx");
  assert.match(page, /const canInvite = can\("team", "write"\);/);
  assert.match(page, /actions=\{canInvite \? \(/);
  // Every place the words appear is behind the permission: the header's button and the empty list's action.
  const offers = [...page.matchAll(/Invite Member/g)].length;
  assert.equal(offers, 2, "the Team screen says Invite Member somewhere this test has not read");
  assert.match(page, /<EmptyStateAction requires=\{\["team", "write"\]\}[\s\S]{0,120}?label="Invite Member"/);
});

test("a list of members that could not be read is not an empty one", () => {
  const page = code("app/team/page.tsx");
  assert.match(page, /catch \(e\) \{\s*setListUnread\(true\);/);
  assert.match(page, /\{loading \|\| listUnread \? "—" : card\.value\}/, "a tile shows a count after a failed read");
  assert.match(page, /sub: loading \|\| listUnread \? "Active members" : `\$\{activeMembers\.length\} active`/, "the first tile counts the active members after a failed read");
  // The unread branch is asked before the empty one.
  const unread = page.indexOf(") : listUnread ? (");
  const empty = page.indexOf(") : members.length === 0 ? (");
  assert.ok(unread > 0 && empty > unread, "the empty list is decided before asking whether the list was read at all");
});

test("the Partner guard calls the area by the name it has", () => {
  const guard = code("components/practice/PartnerGuard.tsx");
  assert.match(guard, /My practice/);
  assert.doesNotMatch(guard, /Revenue Operations|Practice workspace/);
});
