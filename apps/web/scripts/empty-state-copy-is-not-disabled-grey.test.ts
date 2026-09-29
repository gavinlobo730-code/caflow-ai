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
  assert.ok(!src.includes('<p className="text-xs text-ps-disabled">Upload returns, notices, Form 16, and other files for this client</p>'),
    "the 'Upload returns, notices, Form 16…' line is still ps-disabled");
  assert.ok(src.includes('<p className="text-xs text-ps-hint">Upload returns, notices, Form 16, and other files for this client</p>'),
    "the empty-state line should read ps-hint, the token for empty-state copy");
});
