// POST-A-542 (the role walk of 21-11-2026): a People screen says in words when the person may not read it, the Team screen
// offers Invite only to somebody who can invite, and a list that could not be read is not an empty one.
//   node --experimental-strip-types --test scripts/a-people-screen-says-when-it-is-withheld.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { PRACTICE_PEOPLE_SECTIONS } from "../lib/workspace/practiceWorkspace.ts";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(import.meta.dirname, "..");
const code = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

test("every People screen sits under a layout that asks the gate", () => {
  // The RULE, over the one list of People screens: a screen added to the list with no gate above it fails here.
  for (const s of PRACTICE_PEOPLE_SECTIONS) {
    const parts = s.href.split("/").filter(Boolean);
    assert.ok(fs.existsSync(path.join(WEB, "app", ...parts, "page.tsx")), `${s.href} has no page`);
    let gated = false;
    for (let depth = parts.length; depth >= 1 && !gated; depth--) {
      const layout = path.join("app", ...parts.slice(0, depth), "layout.tsx");
      gated = fs.existsSync(path.join(WEB, layout)) && /<PeopleAccessGate>\{children\}<\/PeopleAccessGate>/.test(code(layout));
    }
    assert.ok(gated, `${s.href} has no layout that wraps it in PeopleAccessGate`);
  }
});

test("the gate asks the screen's own pair from the one list, and waits until the permissions are known", () => {
  const gate = code("components/team/PeopleAccessGate.tsx");
  assert.match(gate, /peopleSectionAt\(pathname \?\? ""\)/);
  assert.match(gate, /resolved && section && !can\(section\.requires\[0\], section\.requires\[1\]\)/);
  assert.doesNotMatch(gate, /userRole|"Partner"|"Manager"/, "the gate asks a role where it should ask the permission the server asks");
  assert.match(gate, /that is not the same as there being nothing or nobody/);
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
