// A lot recorded on FORM GST ITC-04 is retracted from one button, offered only to someone the route admits (POST-A-418). Run with:
//   node --experimental-strip-types --test scripts/a-lot-recorded-on-itc-04-is-retracted-from-one-button-offered-to-those-who-may.test.ts
//
// The server's door is `POST /api/sales-cycle/challans/{id}/returns/{lot}/retract` (rbac invoice/write). This holds the screen's half from the source:
//   * the API wrapper reaches it by POST for one challan, one lot and one client, with the reason;
//   * the panel offers "Retract" only where `can("invoice", "write")`, only on a row that carries a lot id (a row derived from a whole-challan return has none), requires a reason,
//     and says in words that the product does not know whether the period was furnished on the portal.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.join(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");
const PANEL = "components/gst/Itc04Panel.tsx";

test("the API wrapper retracts one lot of one challan of one client by POST, with the reason", () => {
  const api = read("lib/api/index.ts");
  const at = api.indexOf("retractChallanReturn:");
  assert.ok(at > 0);
  const body = api.slice(at, at + 520);
  assert.match(body, /\/api\/sales-cycle\/challans\/\$\{challanId\}\/returns\/\$\{lotId\}\/retract/);
  assert.match(body, /method: "POST"/);
  assert.match(body, /client_id: clientId, reason/);
});

test("the panel offers Retract only to a person who may write invoices, only on a lot row, and asks for a reason", () => {
  const src = read(PANEL);
  assert.match(src, /can\("invoice", "write"\)/);
  assert.match(src, /mayRetract && \(/);
  assert.match(src, /r\.lot_id \? \(/);
  assert.match(src, /Say why the lot is being retracted/);
  assert.match(src, /already been furnished, the correction has to be made on the portal as well/);
});
