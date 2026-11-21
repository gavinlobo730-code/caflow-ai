// POST-A-538: the server's copy of the list of screens is the web app's own inventory, the guide is drawn from the product's
// own words, and the tips it replaced are gone.
//   node --experimental-strip-types --test scripts/the-guide-reads-the-one-list-of-screens.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { CATALOGUE, catalogueText } from "./write-guide-screens.mjs";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");
const code = (rel: string) => stripComments(read(rel));

test("the server's list of screens is the inventory as it stands", () => {
  assert.ok(fs.existsSync(CATALOGUE), "apps/api/domain/guide/screens.json is missing");
  assert.equal(
    fs.readFileSync(CATALOGUE, "utf8"), catalogueText(),
    "lib/navigation/screens.ts changed and the server's copy did not: run `node --experimental-strip-types scripts/write-guide-screens.mjs` in apps/web",
  );
});

test("the box draws the product's own words and never the server's text", () => {
  const box = code("components/guide/WhereIsGuide.tsx");
  // What the server sends is read for ids only, and each id becomes a screen through the inventory.
  assert.match(box, /answersFor\(ids, offered, openClient, places\)/);
  assert.match(box, /\{a\.name\}/);
  assert.match(box, /\{sentenceFor\(a\)\}/);
  assert.doesNotMatch(box, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(box, /\.sentence\b|\.answer\b|\.text\b/, "the box reads a sentence off the server's answer");
});

test("the notice about who reads the question is on the box, and the input points at it", () => {
  const box = code("components/guide/WhereIsGuide.tsx");
  assert.match(box, /<AiDisclosure surface="guide" id=\{noticeId\} \/>/);
  assert.match(box, /aria-describedby=\{noticeId\}/);
});

test("a failed ask becomes a plain search that says it is one, with the reason", () => {
  const box = code("components/guide/WhereIsGuide.tsx");
  assert.match(box, /catch \(e\) \{[\s\S]*?plainSearch\(asked, offered\)[\s\S]*?reason/);
  assert.match(box, /this is a plain search of the screens&apos; names\. \{outcome\.reason\}/);
  // "No screen matches" is said by whichever of the two looked.
  assert.match(box, /No screen in PracticeSync matches that\./);
  assert.match(box, /The plain search found no screen with those words\./);
});

test("the guide is on both bars, opened from one place, and both bars pass it down", () => {
  const cluster = code("components/shell/UtilityCluster.tsx");
  assert.match(cluster, /onClick=\{onOpenGuide\}/);
  assert.match(cluster, /Where is…\?/);
  for (const bar of ["components/shell/ClientTopBar.tsx", "components/shell/WorkspaceTopBar.tsx"]) {
    assert.match(code(bar), /<UtilityCluster orientation="[a-z-]+" onOpenSearch=\{onOpenSearch\} onOpenGuide=\{onOpenGuide\} \/>/, bar);
  }
  const shell = code("components/AppShell.tsx");
  assert.equal((shell.match(/<WhereIsGuide\b/g) ?? []).length, 1, "the guide's dialog is drawn more than once, or not at all");
  assert.equal((shell.match(/onOpenGuide=\{\(\) => setGuideOpen\(true\)\}/g) ?? []).length, 2);
});

test("the guide calls each area of the firm menu by the name the menu gives it", async () => {
  // `workspaceConfig.ts` imports icons and cannot be loaded here, so its id and label pairs are read from its source.
  const config = code("lib/workspace/workspaceConfig.ts");
  const pairs = [...config.matchAll(/\bid: "([a-z]+)",\s*label: "([^"]+)"/g)].map((m) => [m[1], m[2]]);
  assert.ok(pairs.length >= 13, "the menu's areas could not be read from workspaceConfig.ts: has its shape changed?");
  const { AREA_NAMES } = await import("../lib/guide/whereIs.ts");
  assert.deepEqual(AREA_NAMES, Object.fromEntries(pairs), "the guide's names for the menu's areas are not the menu's own");
  // And the box works the person's areas out the way the menu does.
  const box = code("components/guide/WhereIsGuide.tsx");
  assert.match(box, /WORKSPACE_CONFIGS\.filter\(\(ws\) => areaOn\(ws\.id\)\)/);
  assert.match(code("components/shell/WorkspaceMegaMenu.tsx"), /WORKSPACE_CONFIGS\.filter\(\(ws\) => areaOn\(ws\.id\)\)/);
});

test("the guided tips are gone: no file, no mark on a screen, no call", () => {
  for (const gone of ["lib/tips", "components/tips", "components/settings/GuidedTipsCard.tsx", "scripts/drive/weekly/guidedTips.mjs"]) {
    assert.ok(!fs.existsSync(path.join(WEB, gone)), `${gone} is back`);
  }
  const walk = (dir: string): string[] => fs.readdirSync(path.join(WEB, dir), { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? (e.name === "node_modules" || e.name === ".next" ? [] : walk(`${dir}/${e.name}`)) : /\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name) ? [`${dir}/${e.name}`] : []);
  const marked = ["app", "components", "lib"].flatMap(walk).filter((f) => /data-tip=|guidedTips|GuidedTip/.test(code(f)));
  assert.deepEqual(marked, [], "these files still carry a guided tip's mark or call");
});
