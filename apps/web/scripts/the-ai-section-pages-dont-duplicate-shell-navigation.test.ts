// sweep-misc-tools-13: /ai-assistant rendered a page-level "&larr; Dashboard"
// breadcrumb above its heading; its sibling in the same AI section, /copilot,
// has never had an equivalent one. The shell rail already provides a way
// back to Home on every page (the one-shell decision), so the fix removes
// the outlier rather than adding a matching breadcrumb to /copilot.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-ai-section-pages-dont-duplicate-shell-navigation.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripComments } from "./stripComments.ts";

const AI_ASSISTANT_PAGE = "app/ai-assistant/page.tsx";
const COPILOT_PAGE = "app/copilot/page.tsx";

test("neither AI-section page links back to \"/\" as its own breadcrumb", () => {
  for (const page of [AI_ASSISTANT_PAGE, COPILOT_PAGE]) {
    const src = stripComments(readFileSync(page, "utf8"));
    assert.doesNotMatch(
      src,
      /href="\/"/,
      `${page} carries a page-level link back to "/" — the shell rail ` +
        "already provides that, and its sibling in the AI section has none",
    );
    assert.doesNotMatch(
      src,
      /Dashboard/,
      `${page} still mentions a "Dashboard" breadcrumb`,
    );
  }
});

test("the /ai-assistant page no longer imports next/link for a breadcrumb it doesn't have", () => {
  const src = readFileSync(AI_ASSISTANT_PAGE, "utf8");
  assert.doesNotMatch(
    src,
    /from "next\/link"/,
    `${AI_ASSISTANT_PAGE} still imports next/link but has nothing left to use it for`,
  );
});
