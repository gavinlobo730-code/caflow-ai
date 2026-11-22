// POST-A-543: the screen where a Partner ticks a person's permissions is grouped under the firm menu's own names, previews
// that person's menu with the menu's own arithmetic, and is offered only to somebody who may save it.
//   node --experimental-strip-types --test scripts/the-tick-screen-sits-under-the-menus-names.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(import.meta.dirname, "..");
const code = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

test("the drawer groups the ticks by the one table's areas and names them the way the menu does", () => {
  const drawer = code("components/team/MemberAccessDrawer.tsx");
  // The names it uses are read off the import, whatever else is imported beside them (the Settings group's id joined them, POST-A-545).
  const imported = drawer.match(/import \{ ([^}]*) \} from "@\/lib\/access\/permissionGroups";/)?.[1].split(", ") ?? [];
  for (const name of ["menuFor", "menuGroups", "menuPermissionKeys", "pairWords", "wouldHold", "SETTINGS_GROUP"]) {
    assert.ok(imported.includes(name), `the drawer does not take ${name} from the one module that groups the ticks`);
  }
  assert.match(drawer, /group\.areaId === SETTINGS_GROUP \? "Settings"/, "the Settings group is named by something other than its own id");
  assert.match(drawer, /Settings is on everybody's menu/, "the Settings group is said to be put on the menu by a tick");
  assert.match(drawer, /import \{ AREA_NAMES \} from "@\/lib\/guide\/whereIs";/, "the areas are named by a list of the drawer's own");
  assert.match(drawer, /MENU_GROUPS\.map\(\(group\) =>/);
  assert.match(drawer, /pairWords\(mp\.resource, mp\.action\)/, "a permission that decides the menu is shown under a technical name");
  assert.match(drawer, /Puts \$\{area\} on the menu\./);
  // What is left over is one group beneath, and it is what is NOT in the table: nothing is listed twice or dropped.
  assert.match(drawer, /pairs\.filter\(\(p\) => !ON_THE_MENU\.has\(`\$\{p\.resource\}:\$\{p\.action\}`\)\)/);
  assert.match(drawer, /<details data-inside-screens>/);
});

test("the preview is the menu's own rule over the choices in the drawer, and says when it is of a draft", () => {
  const drawer = code("components/team/MemberAccessDrawer.tsx");
  assert.match(drawer, /menuFor\(wouldHold\(grid\.role_defaults, draft\), isPartner\)/);
  assert.match(drawer, /\{dirty \? "Their menu once you save" : "Their menu now"\}/);
  assert.match(drawer, /nothing has changed until you save/);
  assert.match(drawer, /My practice is a Partner&apos;s alone and no permission here opens it/);
  // The preview's arithmetic is the firm menu's, not a second copy of it.
  const groups = code("lib/access/permissionGroups.ts");
  assert.match(groups, /areaOffered\(id, \{ can, isPartner \}\)/);
  assert.match(groups, /return outerMenu\(offered\);/);
});

test("the drawer still sends only what changed, and still takes the server's answer after a save", () => {
  const drawer = code("components/team/MemberAccessDrawer.tsx");
  assert.match(drawer, /api\.identity\.setMemberPermissions\(userId, changes\)/);
  assert.match(drawer, /setGrid\(res\.data\);/);
});

test("Edit is offered on the Permissions tab only to somebody who may save a person's access", () => {
  const page = code("app/team/page.tsx");
  assert.match(page, /const mayEditAccess = can\("team", "write"\);/);
  assert.match(page, /\{mayEditAccess && \(\s*<button[^>]*\s+type="button"\s+onClick=\{\(\) => setAccessFor\(member\.id\)\}/);
  // And the server asks that pair of the save.
  const identity = fs.readFileSync(path.join(WEB, "..", "api", "routers", "identity.py"), "utf8");
  const at = identity.indexOf('@router.put("/users/{user_id}/permissions")');
  assert.ok(at >= 0, "the save route has moved");
  assert.match(identity.slice(at, identity.indexOf("@router.", at + 1)), /rbac\("team", "write"\)/);
});
