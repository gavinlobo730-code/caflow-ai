// Every fetch of the fixed-assets COLLECTION endpoint uses the canonical
// (no-trailing-slash) shape, so it never costs a 307 round trip.
//
// THE DEFECT. `routers/fixed_assets.py` registers the collection routes as
// `@router.get("")` / `@router.post("")` under `prefix="/api/fixed-assets"` —
// so the canonical path is `/api/fixed-assets`, with NO trailing slash.
// FastAPI (Starlette, `redirect_slashes=True` by default, and nothing in this
// codebase turns it off) answers a request for `/api/fixed-assets/` — one
// slash further — with a 307 redirect to the path that is actually
// registered. Three call sites on the fixed-assets screen spelled the
// trailing-slash form (the POST that adds an asset, and two of the GETs that
// list assets), so those three fetches paid a second Singapore-to-Mumbai
// round trip that the rest of the screen's calls never did — silently, since
// a 307 still resolves to the right data and nothing in the response says a
// redirect happened.
//
// Run with: node --experimental-strip-types --test scripts/fixed-assets-no-redirect.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const API = path.join(WEB, "..", "api");

const PAGE = path.join(WEB, "app/clients/[id]/fixed-assets/page.tsx");
const ROUTER = path.join(API, "routers/fixed_assets.py");

test("the backend still declares the collection route with no trailing slash", () => {
  // A vacuity guard as much as an assertion: if the canonical shape ever
  // changes (say, to `@router.get("/")`), this file's whole premise — and the
  // frontend fix below — moves with it, and this is what would need to change
  // first.
  const src = fs.readFileSync(ROUTER, "utf8");
  assert.match(src, /APIRouter\(prefix="\/api\/fixed-assets"/,
    "the fixed-assets router's prefix moved — this guard assumes /api/fixed-assets");
  assert.match(src, /@router\.get\(""\)/,
    "the collection GET is no longer registered as the bare prefix — re-check which shape avoids a redirect");
  assert.match(src, /@router\.post\(""\)/,
    "the collection POST is no longer registered as the bare prefix — re-check which shape avoids a redirect");
});

test("no live fetch spells the collection endpoint with a trailing slash", () => {
  const src = stripComments(fs.readFileSync(PAGE, "utf8"));
  // Matches "/api/fixed-assets/" immediately closed by a quote/backtick or
  // followed by "?" — i.e. the bare collection path with one slash too many.
  // A sub-path (`/api/fixed-assets/categories`, `/api/fixed-assets/${id}`,
  // `/api/fixed-assets/movement`, …) is a real, registered route and is never
  // matched, because nothing there is immediately followed by a closing quote
  // or a "?".
  const offender = /\/api\/fixed-assets\/[`"?]/;
  const match = src.match(offender);
  assert.equal(match, null,
    `found \`${match?.[0]}\` — the fixed-assets collection endpoint is registered ` +
    "with no trailing slash (see the previous test), so this spelling costs a 307 redirect");
});
