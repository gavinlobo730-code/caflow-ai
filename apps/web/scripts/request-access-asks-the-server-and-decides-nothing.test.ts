// POST-A-543, Request access: the notice offers it for the permission it named, the button decides nothing, and the
// Approvals page says the request in a person's words and sends no stock reason on a decline.
//   node --experimental-strip-types --test scripts/request-access-asks-the-server-and-decides-nothing.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(import.meta.dirname, "..");
const code = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

test("the one gate offers the request for exactly the permission its notice named", () => {
  const gate = code("components/auth/ScreenAccessGate.tsx");
  assert.match(gate, /<RequestAccess key=\{`\$\{answer\.ask\[0\]\}:\$\{answer\.ask\[1\]\}`\} resource=\{answer\.ask\[0\]\} action=\{answer\.ask\[1\]\} askedFrom=\{what\} \/>/);
  // My practice is never offered it: the gate returns the page (and its own Partner guard) before the notice is drawn.
  assert.match(gate, /if \(!answer \|\| answer\.allowed \|\| answer\.partnerOnly \|\| !answer\.ask\) return <>\{children\}<\/>;/);
});

test("the button reads the person's own requests first, sends what was typed, and shows the server's words on a refusal", () => {
  const button = code("components/auth/RequestAccess.tsx");
  assert.match(button, /api\.approvals\.myAccessRequests\(\)/);
  assert.match(button, /readMine\(res\.data\)/, "the answer is used without being read by kind");
  assert.match(button, /api\.approvals\.requestAccess\(\{ resource, action, asked_from: askedFrom, note: note\.trim\(\) \|\| undefined \}\)/);
  assert.match(button, /failureSentence\(e, "The request could not be sent\."\)/);
  assert.match(button, /if \(standing\?\.kind === "waiting"\)/);
  // It decides nothing about who may ask or for what: no role and no permission is consulted here.
  assert.doesNotMatch(button, /userRole|usePermissions|can\(/);
});

test("the two calls go to the request's own door, which every member of staff may use", () => {
  const api = code("lib/api/index.ts");
  assert.match(api, /"\/api\/approvals\/access-requests", \{ method: "POST"/);
  assert.match(api, /"\/api\/approvals\/access-requests\/mine"/);
  const router = fs.readFileSync(path.join(WEB, "..", "api", "routers", "approvals.py"), "utf8");
  const post = router.slice(router.indexOf('@router.post("/access-requests")'));
  assert.match(post.slice(0, post.indexOf("@router.", 1)), /rbac\("identity", "write"\)/);
  const mine = router.slice(router.indexOf('@router.get("/access-requests/mine")'));
  assert.match(mine.slice(0, mine.indexOf("@router.", 1)), /rbac\("identity", "read"\)/);
});

test("the Approvals page says the request in a person's words, asks before giving it, and sends the Partner's own reason on a decline", () => {
  const page = code("app/approvals/page.tsx");
  assert.match(page, /import \{ pairWords \} from "@\/lib\/access\/permissionGroups";/);
  assert.match(page, /`\$\{r\.payload\.user_name\} asks to: \$\{accessWords\(r\)\}`/);
  assert.match(page, /title: "Give this access\?"/);
  // The reason sent on a decline is what the Partner typed, or nothing: never the stock phrase.
  assert.match(page, /if \(action === "reject" && request\?\.request_type === ACCESS_REQUEST\) \{/);
  assert.match(page, /declineReason = typed\.trim\(\) \|\| undefined;/);
  assert.match(page, /if \(typed === null\) return;/, "closing the question still declines the request");
  // The type's name is the server's.
  const service = fs.readFileSync(path.join(WEB, "..", "api", "services", "access_request_service.py"), "utf8");
  assert.match(service, /REQUEST_TYPE = "access_request"/);
  assert.match(code("lib/access/accessRequest.ts"), /export const ACCESS_REQUEST = "access_request";/);
});
