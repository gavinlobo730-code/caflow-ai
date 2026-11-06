// A request to PostgREST that gets no answer comes back with the product's sentence (POST-A-413):
//   node --experimental-strip-types --test lib/supabase/plainRestFetch.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { createClient } from "@supabase/supabase-js";
import { browserFailureOf, failureSentence, NO_ANSWER_CODE, NO_ANSWER_READ, NO_ANSWER_WRITE } from "../api/failureSentence.ts";
import { makePlainRestFetch } from "./plainRestFetch.ts";

const REST = "https://example.supabase.co/rest/v1/clients";
const AUTH = "https://example.supabase.co/auth/v1/token?grant_type=refresh_token";

/** What each engine rejects `fetch` with when the connection is gone. */
const DROPPED = [
  ["Chrome", "Failed to fetch"],
  ["Firefox", "NetworkError when attempting to fetch resource."],
  ["Safari", "Load failed"],
  ["Node", "fetch failed"],
] as const;

function rejecting(e: unknown): typeof fetch {
  return (async () => {
    throw e;
  }) as typeof fetch;
}

async function bodyOf(res: Response): Promise<{ message: string; details: string; hint: string; code: string }> {
  return (await res.json()) as { message: string; details: string; hint: string; code: string };
}

test("an answer to something that is not PostgREST is passed through as the very response it was", async () => {
  const answer = new Response("{}", { status: 200 });
  const through = makePlainRestFetch((async () => answer) as typeof fetch);
  assert.equal(await through(AUTH), answer);
});

test("an answer from PostgREST is handed on with its status, its headers and its body", async () => {
  const answer = new Response('[{"id":1}]', { status: 206, statusText: "Partial Content", headers: { "content-range": "0-0/5", "x-kept": "yes" } });
  const res = await makePlainRestFetch((async () => answer) as typeof fetch)(REST);
  assert.equal(res.status, 206);
  assert.equal(res.statusText, "Partial Content");
  assert.equal(res.headers.get("content-range"), "0-0/5");
  assert.equal(res.headers.get("x-kept"), "yes");
  assert.equal(await res.text(), '[{"id":1}]');
  // a status that carries no body is handed on with none (a Response cannot be built with one)
  const none = await makePlainRestFetch((async () => new Response(null, { status: 204 })) as typeof fetch)(REST, { method: "PATCH" });
  assert.equal(none.status, 204);
  assert.equal(await none.text(), "");
  // and an empty body under a 200 (a count) is an empty body
  const head = await makePlainRestFetch((async () => new Response("", { status: 200, headers: { "content-range": "*/12" } })) as typeof fetch)(REST, { method: "HEAD" });
  assert.equal(head.headers.get("content-range"), "*/12");
});

/** An answer whose headers arrived and whose body then died, as a connection that drops half way does. */
function bodyThatDies(words: string, status = 200): typeof fetch {
  return (async () => new Response(new ReadableStream({ start(controller) { controller.error(new TypeError(words)); } }), { status })) as typeof fetch;
}

test("a connection that dies after the headers is the same drop: the body is read here and the sentence is given", async () => {
  for (const [engine, words] of [["Chrome", "network error"], ["Firefox", "NetworkError when attempting to fetch resource."], ["Safari", "Load failed"], ["Node", "terminated"]] as const) {
    const read = await makePlainRestFetch(bodyThatDies(words))(REST, { method: "GET" });
    assert.equal(read.status, 503, engine);
    assert.equal((await bodyOf(read)).message, NO_ANSWER_READ, engine);
    // a change whose answer began and then died: it is not known how it ended
    const write = await makePlainRestFetch(bodyThatDies(words, 201))(REST, { method: "POST" });
    assert.equal((await bodyOf(write)).message, NO_ANSWER_WRITE, engine);
  }
  // a body that dies for a reason that is not a dropped connection is not answered for
  await assert.rejects(() => makePlainRestFetch(bodyThatDies("Invalid state"))(REST), /Invalid state/);
});

test("a dropped connection to PostgREST is answered, in the server's place, with the sentence for a read", async () => {
  for (const [engine, words] of DROPPED) {
    const res = await makePlainRestFetch(rejecting(new TypeError(words)))(REST, { method: "GET" });
    assert.equal(res.status, 503, engine);
    assert.match(res.headers.get("content-type") ?? "", /json/);
    const body = await bodyOf(res);
    assert.equal(body.message, NO_ANSWER_READ, engine);
    assert.equal(body.code, NO_ANSWER_CODE, engine);
    assert.equal(body.details, "");
    assert.equal(body.hint, "");
  }
});

test("a change that got no answer says that it is not known whether it went through, however the method is given", async () => {
  const dropped = makePlainRestFetch(rejecting(new TypeError("Failed to fetch")));
  for (const method of ["POST", "PATCH", "DELETE", "PUT", "post"]) {
    assert.equal((await bodyOf(await dropped(REST, { method }))).message, NO_ANSWER_WRITE, method);
  }
  // the method may be on a Request, not in the options
  assert.equal((await bodyOf(await dropped(new Request(REST, { method: "POST", body: "{}" })))).message, NO_ANSWER_WRITE);
  assert.equal((await bodyOf(await dropped(new Request(REST)))).message, NO_ANSWER_READ);
  // …and a HEAD (a count) only asks
  assert.equal((await bodyOf(await dropped(REST, { method: "HEAD" }))).message, NO_ANSWER_READ);
  // with no method at all it is a GET
  assert.equal((await bodyOf(await dropped(REST))).message, NO_ANSWER_READ);
  assert.equal((await bodyOf(await dropped(new URL(REST)))).message, NO_ANSWER_READ);
});

test("what is not the browser's report of a dropped connection, or not a request to PostgREST, is thrown as it was", async () => {
  const same = async (url: string, e: unknown, why: string) => {
    await assert.rejects(
      () => makePlainRestFetch(rejecting(e))(url, { method: "GET" }),
      (thrown: unknown) => thrown === e,
      why,
    );
  };
  // sign-in is read by its own screens
  await same(AUTH, new TypeError("Failed to fetch"), "a request to the auth service was answered by this module");
  // a request somebody cancelled, or that ran out of time, is not a dropped connection
  const aborted = new DOMException("The operation was aborted.", "AbortError");
  await same(REST, aborted, "an aborted request was answered as a dropped connection");
  const timedOut = new DOMException("The operation timed out.", "TimeoutError");
  await same(REST, timedOut, "a request that ran out of time was answered as a dropped connection");
  // a programming error stays the programming error it is
  await same(REST, new TypeError("Failed to construct 'Request': Invalid URL"), "a programming TypeError was answered as a dropped connection");
  await same(REST, new Error("Load failed"), "a plain Error that carries a common word was answered as a dropped connection");
  await same(REST, "not an error", "a thrown string was answered as a dropped connection");
});

// ── the real client, given this fetch ────────────────────────────────────────────────────────────────────────────────────

function clientWith(base: typeof fetch) {
  return createClient("https://example.supabase.co", "anon-key", {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    global: { fetch: makePlainRestFetch(base) },
  });
}

test("the client returns the sentence as the error's message, for a change and for a read", async () => {
  let calls = 0;
  const client = clientWith((async () => {
    calls++;
    throw new TypeError("Failed to fetch");
  }) as typeof fetch);

  const write = await client.from("clients").insert({ legal_name: "A" });
  assert.equal(write.error?.message, NO_ANSWER_WRITE);
  assert.equal(write.error?.code, NO_ANSWER_CODE);
  assert.equal(write.status, 503);
  assert.equal(write.data, null);
  assert.equal(calls, 1, "a change was sent more than once");

  calls = 0;
  const read = await client.from("clients").select("id").limit(1).retry(false);
  assert.equal(read.error?.message, NO_ANSWER_READ);
  assert.equal(read.status, 503);
  assert.equal(calls, 1);

  // a body that died after the headers is told the same way, by the real client
  const dying = clientWith(bodyThatDies("network error"));
  assert.equal((await dying.from("clients").select("id").limit(1).retry(false)).error?.message, NO_ANSWER_READ);
  assert.equal((await dying.from("clients").insert({ legal_name: "A" })).error?.message, NO_ANSWER_WRITE);
});

test("the error the client hands back is said for what the screen was doing, by its code (a plain object, not an Error)", async () => {
  const client = clientWith(rejecting(new TypeError("Failed to fetch")));
  const { error } = await client.from("clients").insert({ legal_name: "A" });
  assert.ok(error && !(error instanceof Error), "the client's error is a plain object, and the screens that read it must be able to say it");
  assert.equal(browserFailureOf(error), "no_answer");
  assert.equal(failureSentence(error, "Couldn't save.", "write"), NO_ANSWER_WRITE);
  assert.equal(failureSentence(error, "Couldn't load.", "read"), NO_ANSWER_READ);
  // a refusal the database sent is not worded as a dropped connection
  const refusal = clientWith((async () => new Response(JSON.stringify({ message: "permission denied for table clients", details: null, hint: null, code: "42501" }), { status: 403 })) as typeof fetch);
  const denied = (await refusal.from("clients").select("id").limit(1).retry(false)).error;
  assert.equal(browserFailureOf(denied), null);
  assert.equal(failureSentence(denied, "Couldn't load."), "Couldn't load.");
});

test("the client still sends a read again, up to three times, before it gives the sentence", async (t) => {
  // The module's header says the status is 503 so that the client keeps its own policy for a dropped connection; this holds that to the library it describes.
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  const client = clientWith((async () => {
    calls++;
    throw new TypeError("Failed to fetch");
  }) as typeof fetch);
  let answer: { error: { message: string } | null } | undefined;
  const reading = Promise.resolve(client.from("clients").select("id").limit(1)).then((a) => {
    answer = a;
  });
  for (let i = 0; i < 40 && answer === undefined; i++) {
    await new Promise((resolve) => setImmediate(resolve));
    t.mock.timers.tick(4_000);
  }
  await reading;
  assert.equal(calls, 4, "the read was not sent one more time on each of three retries");
  assert.equal(answer?.error?.message, NO_ANSWER_READ);
});

test("the client's own sentence for a thrown error is the product's too", async () => {
  const client = clientWith(rejecting(new TypeError("Load failed")));
  await assert.rejects(
    async () => {
      await client.from("clients").update({ legal_name: "B" }).eq("id", "1").throwOnError();
    },
    (e: unknown) => (e as Error).message === NO_ANSWER_WRITE,
  );
});

test("an answer the database itself sent is left as it is", async () => {
  const refusal = JSON.stringify({ message: "permission denied for table clients", details: null, hint: null, code: "42501" });
  const client = clientWith((async () => new Response(refusal, { status: 403, headers: { "Content-Type": "application/json" } })) as typeof fetch);
  const answer = await client.from("clients").select("id").limit(1).retry(false);
  assert.equal(answer.error?.message, "permission denied for table clients");
  assert.equal(answer.error?.code, "42501");
});
