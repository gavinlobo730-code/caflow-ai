// Two empty-state helper sentences used `text-ps-disabled` — the token
// `tailwind.config.ts` deliberately leaves failing WCAG 1.4.3, reserved for a
// genuinely inactive control — on ordinary informational copy, making both
// close to unreadable. `text-ps-hint` is the token the palette names for
// exactly this ("hints, placeholders, empty states").
//
// Run with:
//   node --experimental-strip-types --test scripts/empty-state-copy-is-not-disabled-grey.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

test("the AI Insights helper sentence reads as a hint, not a disabled control", () => {
  const src = fs.readFileSync(path.join(WEB, "app/clients/[id]/ai-insights/page.tsx"), "utf8");
  assert.ok(!src.includes('<p className="text-xs text-ps-disabled max-w-sm mx-auto">'),
    "the helper sentence explaining how to generate insights is still ps-disabled");
  assert.ok(src.includes('<p className="text-xs text-ps-hint max-w-sm mx-auto">'),
    "the helper sentence should read ps-hint, the token for empty-state copy");
});

test("the Documents empty-state line reads as a hint, not a disabled control", () => {
  const src = fs.readFileSync(path.join(WEB, "app/clients/[id]/documents/page.tsx"), "utf8");
  // The sentence is the description of the shared EmptyState now (frontend_ux-24),
  // so the rule is asked in two halves: nothing on this page paints that copy
  // `ps-disabled`, and the shared component paints every description `ps-hint`.
  assert.ok(!/text-ps-disabled[^"]*"[^>]*>[^<]*Form 16/.test(src),
    "the Documents empty-state copy is painted ps-disabled");
  assert.match(src, /description="[^"]*Form 16[^"]*"/,
    "the Documents empty state should carry its explanation as the EmptyState description");
  const states = fs.readFileSync(path.join(WEB, "components/ui/states.tsx"), "utf8");
  assert.match(states, /\{description && <p className="[^"]*text-ps-hint[^"]*">\{description\}<\/p>\}/,
    "EmptyState's description should read ps-hint, the token for empty-state copy");
});
