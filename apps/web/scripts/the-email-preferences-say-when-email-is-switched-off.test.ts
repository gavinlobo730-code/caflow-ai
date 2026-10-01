// A switch a person can tick for mail that cannot arrive is a label that promises more than the code does.
// Run with:
//   node --experimental-strip-types --test scripts/the-email-preferences-say-when-email-is-switched-off.test.ts
//
// WHY THIS EXISTS
//     The practice's own mail has one firm-wide switch (PRACTICE_MAIL_ENABLED, off unless set). While it is off, the
//     "Email me when" screen still lets a person choose, and their choices are saved, so the screen has to say that
//     nothing will arrive yet. The server serves `mail_enabled` on the preferences payload for exactly this.
//
//     THE RULE IS THE THREE-STATE ONE: a missing `mail_enabled` (a backend that has not been redeployed yet) is
//     "not told", and is never rendered as "off" — a notice that says email is off when it is on is the opposite
//     defect and as wrong. Only an explicit `false` shows it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const ROOT = path.join(import.meta.dirname, "..");
const PANEL = stripComments(fs.readFileSync(path.join(ROOT, "components/notifications/EmailPreferencesPanel.tsx"), "utf8"));
const CLIENT = stripComments(fs.readFileSync(path.join(ROOT, "lib/api/index.ts"), "utf8"));

test("the panel keeps three states and reads only a real boolean from the server", () => {
  assert.match(PANEL, /useState<boolean \| null>\(null\)/, "unknown must be its own state");
  assert.match(PANEL, /typeof v === "boolean"/, "a truthy non-boolean must not count as a reading");
});

test("the notice shows on an explicit false and on nothing else", () => {
  assert.match(PANEL, /mailEnabled === false/);
  assert.doesNotMatch(PANEL, /!mailEnabled\b/, "null (not told) must not be read as off");
  assert.doesNotMatch(PANEL, /mailEnabled\s*\?\s*null/, "no truthiness shortcut");
});

test("it says email is off, that the choices are kept, and that the in-app notifications are not affected", () => {
  assert.match(PANEL, /switched off/i);
  assert.match(PANEL, /choices are saved/i);
  assert.match(PANEL, /notifications in the app are not affected/i);
});

test("both the read and the save refresh it, so the notice cannot go stale after a change", () => {
  assert.equal((PANEL.match(/setMailEnabled\(readMailEnabled\(res\.data\)\)/g) ?? []).length, 2);
});

test("the API client types carry the field on both the read and the write", () => {
  const matches = CLIENT.match(/events: EmailPreferenceEvent\[\]; mail_enabled\?: boolean/g) ?? [];
  assert.equal(matches.length, 2);
});
