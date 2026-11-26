import { test } from "node:test";
import assert from "node:assert/strict";
import { EXTRACT_UPLOAD_LIMIT_BYTES, needsReducing, reducedSentence, scaledSize } from "./fitUpload.ts";

const MB = 1024 * 1024;

test("an image that fits is never touched, and only a JPEG or PNG over the limit is reduced", () => {
  assert.equal(needsReducing({ type: "image/jpeg", size: 6 * MB }), false);
  assert.equal(needsReducing({ type: "image/jpeg", size: EXTRACT_UPLOAD_LIMIT_BYTES - 300 * 1024 }), false);
  assert.equal(needsReducing({ type: "image/jpeg", size: 12 * MB }), true);
  // The test is the server's own limit on the file's bytes, not the size a reduction aims for: a photograph the server would accept is sent as taken.
  assert.equal(needsReducing({ type: "image/jpeg", size: EXTRACT_UPLOAD_LIMIT_BYTES - 100 * 1024 }), false, "a photograph just under the limit was reduced");
  assert.equal(needsReducing({ type: "image/jpeg", size: EXTRACT_UPLOAD_LIMIT_BYTES }), false, "a photograph exactly at the limit was reduced");
  assert.equal(needsReducing({ type: "image/png", size: EXTRACT_UPLOAD_LIMIT_BYTES + 1 }), true, "a photograph one byte over the limit was not reduced");
  assert.equal(needsReducing({ type: "image/png", size: 11 * MB }), true);
  assert.equal(needsReducing({ type: "application/pdf", size: 30 * MB }), false, "a PDF is not an image to shrink");
  assert.equal(needsReducing({ type: "image/webp", size: 30 * MB }), false);
});

test("the longer edge is brought to the target, the proportions are kept and nothing is enlarged", () => {
  assert.deepEqual(scaledSize(4000, 3000, 2000), { width: 2000, height: 1500 });
  assert.deepEqual(scaledSize(3000, 4000, 2000), { width: 1500, height: 2000 });
  assert.deepEqual(scaledSize(1200, 900, 2000), { width: 1200, height: 900 });
  assert.deepEqual(scaledSize(0, 0, 2000), { width: 0, height: 0 });
});

test("the sentence names both sizes and says the reduced copy is the one kept", () => {
  const s = reducedSentence(12.4 * MB, 4.1 * MB);
  assert.match(s, /12\.4 MB/); assert.match(s, /4\.1 MB/); assert.match(s, /reduced copy is the one kept/);
});
