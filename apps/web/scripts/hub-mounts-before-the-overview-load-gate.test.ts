// apex-overview-practice-07(a): the Overview page returned a full-page
// skeleton while its own client/tasks/compliance/health Promise.all was
// pending, and only mounted <Hub clientId> AFTER that resolved — although
// Hub's own data has nothing to do with any of those four fetches. This
// pinned all fifteen hub tiles behind the slowest of them (the health score
// calculation is the single heaviest request in the app).
//
// Fix: <Hub clientId={clientId} /> now renders unconditionally, before any
// loading/error/notFound branch, so it starts its own fetch the moment
// clientId resolves.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const PAGE = path.resolve(import.meta.dirname, "..", "app", "clients", "[id]", "overview", "page.tsx");

function read(): string {
  return fs.readFileSync(PAGE, "utf8");
}

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

test("the page no longer early-returns a full skeleton before Hub can mount", () => {
  const code = stripComments(read());
  assert.doesNotMatch(code, /if\s*\(\s*loading\s*\)\s*return/,
    "loading is still an early RETURN — that is exactly what used to keep " +
    "<Hub> from mounting until the client/tasks/compliance/health fetch " +
    "finished");
});

test("<Hub clientId={clientId} /> appears BEFORE any loading/error/notFound branch in the JSX", () => {
  const src = read();
  const returnStart = src.indexOf("return (\n    <div className=\"flex h-full overflow-hidden\">");
  assert.ok(returnStart > -1, "could not find the page's main return statement");
  const body = src.slice(returnStart);

  const hubAt = body.indexOf("<Hub clientId={clientId} />");
  assert.ok(hubAt > -1, "<Hub clientId={clientId} /> is not rendered at all");

  const firstBodyStateBranch = body.indexOf('bodyState === "loading"');
  assert.ok(firstBodyStateBranch > -1, "could not find the loading branch");

  assert.ok(hubAt < firstBodyStateBranch,
    "<Hub> is rendered AFTER the loading branch — it is still gated behind it");
});

test("Hub is rendered exactly once (not duplicated once per bodyState branch)", () => {
  const src = read();
  const count = (src.match(/<Hub clientId=\{clientId\} \/>/g) ?? []).length;
  assert.equal(count, 1, `expected exactly one <Hub> mount, found ${count}`);
});

test("negative control: a page that puts Hub inside the ready branch would fail the ordering check", () => {
  const fakeSrc = `
    return (
      <div>
        {bodyState === "loading" && <Skeleton />}
        {bodyState === "ready" && (
          <>
            <Hub clientId={clientId} />
          </>
        )}
      </div>
    );
  `;
  const hubAt = fakeSrc.indexOf("<Hub clientId={clientId} />");
  const loadingAt = fakeSrc.indexOf('bodyState === "loading"');
  assert.ok(hubAt > loadingAt, "the fake regressed page should have Hub AFTER loading");
});
