/**
 * Group: a phone photograph of a bill, at 390 px (POST-A-131).
 *
 * On a phone, Purchases > New Bill offers a photograph of the supplier's invoice to read. This drives it in Chromium at the width of a phone
 * (390 x 844, touch, so the "Take photo" button is offered):
 *   1. the upload row fits the screen: nothing makes the page scroll sideways;
 *   2. a photograph that already fits the 10 MB limit is sent EXACTLY as it was taken (it is kept as the supplier's invoice, CGST Rule 36(1));
 *   3. one over the limit is reduced before it is sent, the request is under 10 MB, and the screen says it was reduced, with both sizes.
 *
 * NOT PROVED: that a real phone's camera opens (a file chosen through the input stands for what the camera hands over), Android, or iOS Safari.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";
import { until } from "../kit.mjs";

export const group = "phone-photo";
const EXTRACT = /document-intelligence-v1\/extract-invoice$/;
const MB = 1024 * 1024;

/** A noisy JPEG of the given size, made by the browser (noise does not compress, so the file is large and real). */
async function photograph(page, width, height, quality) {
  const b64 = await page.evaluate(async ({ width, height, quality }) => {
    const c = document.createElement("canvas"); c.width = width; c.height = height;
    const ctx = c.getContext("2d"); const img = ctx.createImageData(width, height);
    for (let i = 0; i < img.data.length; i += 4) { img.data[i] = Math.random() * 255; img.data[i + 1] = Math.random() * 255; img.data[i + 2] = Math.random() * 255; img.data[i + 3] = 255; }
    ctx.putImageData(img, 0, 0);
    const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", quality));
    const buf = new Uint8Array(await blob.arrayBuffer()); let s = "";
    for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    return btoa(s);
  }, { width, height, quality });
  return Buffer.from(b64, "base64");
}

async function atTheBill(env) {
  const { page, stub } = env;
  await page.setViewportSize({ width: 390, height: 844 });
  stub.route({ method: "POST", re: EXTRACT, reply: () => ok({ extracted: null }), status: 422 });
  await page.goto(env.at("/purchases/bills/new/edit/"), { waitUntil: "networkidle" });
  await page.getByLabel("Invoice file to extract").waitFor({ timeout: 20000 });
}
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

export const scenarios = [
  {
    id: "the-upload-row-fits-a-390-px-screen",
    title: "Purchases > New Bill at 390 px: the upload row and its buttons fit and the page does not scroll sideways",
    async run(env) {
      await atTheBill(env);
      assert.ok((await sideways(env.page)) <= 0, `the page scrolls sideways by ${await sideways(env.page)} px at 390 px`);
      const box = await env.page.getByRole("button", { name: "Extract", exact: true }).boundingBox();
      assert.ok(box && box.x >= 0 && box.x + box.width <= 390, `the Extract button is off the screen: ${JSON.stringify(box)}`);
    },
  },
  {
    id: "a-photograph-that-fits-is-sent-exactly-as-taken",
    title: "Purchases > New Bill: a 2 MB photograph is sent byte for byte, and nothing says it was reduced",
    async run(env) {
      const { page, stub } = env;
      await atTheBill(env);
      const jpg = await photograph(page, 1400, 1000, 0.9);
      assert.ok(jpg.length < 9 * MB, `the test photograph is ${jpg.length} bytes`);
      await page.getByLabel("Invoice file to extract").setInputFiles({ name: "bill.jpg", mimeType: "image/jpeg", buffer: jpg });
      await page.getByRole("button", { name: "Extract", exact: true }).click();
      await until(async () => stub.writesTo(EXTRACT, "POST").length === 1, "the extraction request");
      const body = stub.writesTo(EXTRACT, "POST")[0].bytes;
      assert.ok(body.includes(jpg), "the file that fits was changed on its way");
      assert.equal(await page.getByText(/was reduced to|so it was reduced/).count(), 0);
    },
  },
  {
    id: "a-photograph-over-ten-megabytes-is-reduced-and-says-so",
    title: "Purchases > New Bill: a photograph over 10 MB is sent under 10 MB, and the screen says it was reduced, from what to what",
    async run(env) {
      const { page, stub } = env;
      await atTheBill(env);
      const jpg = await photograph(page, 4000, 3000, 1);
      assert.ok(jpg.length > 10 * MB, `the test photograph is only ${(jpg.length / MB).toFixed(1)} MB`);
      await page.getByLabel("Invoice file to extract").setInputFiles({ name: "big.jpg", mimeType: "image/jpeg", buffer: jpg });
      await page.getByRole("button", { name: "Extract", exact: true }).click();
      await until(async () => stub.writesTo(EXTRACT, "POST").length === 1, "the extraction request", 30000);
      const sent = stub.writesTo(EXTRACT, "POST")[0].bytes.length;
      assert.ok(sent < 10 * MB, `the request was ${(sent / MB).toFixed(1)} MB`);
      await page.getByText(/over the 10 MB limit, so it was reduced to/).waitFor({ timeout: 5000 });
      assert.match(await page.getByText(/so it was reduced to/).innerText(), /The photograph was \d+\.\d MB.*reduced to \d\.\d MB/);
    },
  },
];
