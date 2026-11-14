/**
 * A KNOWLEDGE-BASE SEARCH READS THE CURRENT TEXT AS WELL AS THE TITLE, AND THE SCREEN SAYS WHERE THE WORDS WERE (POST-A-216),
 * driven in a browser.
 *
 * Against a stubbed server, in Chromium:
 *
 *   1. on the firm's Knowledge Base, an article the server found by its text alone says so under its title, and one found by its
 *      title does not; the words are sent once typing pauses, trimmed;
 *   2. typing a phrase sends one search for the pause, not one per key;
 *   3. an earlier, slower answer that lands after a later one does not replace it: the list is the answer to the words in the box;
 *   4. a search that finds nothing repeats the words and says no article in this list has every one of them in its title or
 *      current text, and does not say there are no articles;
 *   5. on a client's Knowledge tab, an article found by its text alone says so too;
 *   6. on a client's Knowledge tab, the empty sentence describes the answer on screen and not the box: clearing a search that
 *      found nothing never shows "No client-scoped articles." while the client's articles are being read back;
 *   7. a search of more than eight words shows the server's refusal in its own words.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "knowledge-search";

const FIRM_SEARCH = /\/api\/knowledge\/articles\?query=/;
const FOUND = [
  { id: "a-text", title: "Foreign payments", scope: "firm", current_version: 2, tags: [], matched_in: ["text"] },
  { id: "a-title", title: "Form 15CA checklist", scope: "firm", current_version: 1, tags: [], matched_in: ["title"] },
  { id: "a-both", title: "15CA and 15CB together", scope: "firm", current_version: 3, tags: [], matched_in: ["title", "text"] },
];

const box = (page) => page.getByLabel("Search articles");

async function atTheKnowledgeBase(env) {
  const { page } = env;
  await page.goto(`${env.base}/knowledge/`, { waitUntil: "networkidle" });
  await box(page).waitFor();
}

function searchesSent(env, answer = () => ok(FOUND)) {
  const sent = [];
  env.stub.route({ method: "GET", re: FIRM_SEARCH, reply: (req, body, url) => {
    sent.push(url.searchParams.get("query"));
    return answer(url.searchParams.get("query"));
  } });
  return sent;
}

export const scenarios = [
  {
    id: "an-article-found-by-its-text-alone-says-so",
    title: "found by its text alone: says so under the title; found by its title: does not; the words sent trimmed",
    async run(env) {
      const { page } = env;
      const sent = searchesSent(env);
      await atTheKnowledgeBase(env);
      assert.equal(await box(page).getAttribute("placeholder"), "Search titles and text…");
      await box(page).fill("  15CA ");
      await page.getByText("Foreign payments").waitFor();
      assert.deepEqual(sent, ["15CA"]);
      await page.getByTestId("article-a-text-found-in-text").waitFor();
      assert.equal(await page.getByTestId("article-a-text-found-in-text").innerText(),
        "The words are in the article’s text, not its title.");
      assert.equal(await page.getByTestId("article-a-title-found-in-text").count(), 0);
      assert.equal(await page.getByTestId("article-a-both-found-in-text").count(), 0);
    },
  },
  {
    id: "typing-a-phrase-sends-one-search-for-the-pause",
    title: "a phrase typed key by key sends one search once typing pauses",
    async run(env) {
      const { page } = env;
      const sent = searchesSent(env);
      await atTheKnowledgeBase(env);
      await box(page).click();
      await page.keyboard.type("form 15CA", { delay: 40 });
      await page.getByText("Foreign payments").waitFor();
      await page.waitForTimeout(600);
      assert.deepEqual(sent, ["form 15CA"], `searches sent: ${JSON.stringify(sent)}`);
    },
  },
  {
    id: "an-earlier-slower-answer-does-not-replace-a-later-one",
    title: "the slow answer for 'TDS' lands after the answer for 'TDS rent' and the list stays the second",
    async run(env) {
      const { page, stub } = env;
      const sent = [];
      stub.route({ method: "GET", re: /\/api\/knowledge\/articles\?query=TDS$/, delay: 1500, reply: () => {
        sent.push("TDS");
        return ok([{ id: "k-old", title: "Every TDS article", scope: "firm", current_version: 1, tags: [], matched_in: ["title"] }]);
      } });
      stub.route({ method: "GET", re: /\/api\/knowledge\/articles\?query=TDS\+rent$/, reply: () => {
        sent.push("TDS rent");
        return ok([{ id: "k-new", title: "Rent and 194-IB", scope: "firm", current_version: 2, tags: [], matched_in: ["text"] }]);
      } });
      await atTheKnowledgeBase(env);
      await box(page).fill("TDS");
      await until(async () => sent.length === 1, "the search for 'TDS' to reach the server");
      const slowLeft = Date.now();                            // its answer is held for 1.5 s from here
      await box(page).fill("TDS rent");
      await page.getByText("Rent and 194-IB").waitFor();
      assert.deepEqual(sent, ["TDS", "TDS rent"]);
      await page.waitForTimeout(Math.max(0, slowLeft + 1500 + 400 - Date.now()));   // the slow answer has landed
      assert.equal(await page.getByText("Every TDS article").count(), 0, "the earlier answer replaced the later one");
      assert.equal(await page.getByText("Rent and 194-IB").count(), 1);
      assert.equal(await page.getByTestId("article-k-new-found-in-text").count(), 1);
    },
  },
  {
    id: "a-search-that-finds-nothing-says-so",
    title: "no match: says the words are in no title or current text, not that there are no articles",
    async run(env) {
      const { page } = env;
      searchesSent(env, () => ok([]));
      await atTheKnowledgeBase(env);
      await box(page).fill("gratuity");
      await page.getByText("No article in this list has every word of \u201cgratuity\u201d in its title or its current text.").waitFor();
      assert.equal(await page.getByText("No articles found.").count(), 0);
    },
  },
  {
    id: "a-clients-article-found-by-its-text-alone-says-so",
    title: "on a client's Knowledge tab: found by its text alone says so; the words go to the client's own search",
    async run(env) {
      const { page, stub } = env;
      const sent = [];
      stub.route({ method: "GET", re: new RegExp(`/api/clients/${env.clientId}/knowledge\\?query=`), reply: (req, body, url) => {
        sent.push(url.searchParams.get("query"));
        return ok([
          { id: "c-text", title: "Acme quirks", current_version: 2, tags: [], matched_in: ["text"] },
          { id: "c-title", title: "Acme cheque habits", current_version: 1, tags: [], matched_in: ["title", "text"] },
        ]);
      } });
      await page.goto(env.at("/knowledge/"), { waitUntil: "networkidle" });
      const search = page.getByLabel("Search client articles");
      await search.waitFor();
      assert.equal(await search.getAttribute("placeholder"), "Search this client's titles and text…");
      await search.fill("cheque");
      await page.getByText("Acme quirks").waitFor();
      assert.deepEqual(sent, ["cheque"]);
      await page.getByTestId("article-c-text-found-in-text").waitFor();
      assert.equal(await page.getByTestId("article-c-title-found-in-text").count(), 0);
    },
  },
  {
    id: "a-clients-empty-sentence-follows-the-answer-not-the-box",
    title: "client tab: clearing a search that found nothing never says the client has no articles while the list is read back",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("knowledge_articles", [
        { id: "c-1", title: "Acme quirks", current_version: 1, tags: [], updated_at: "2026-11-02T10:00:00+00:00" },
        { id: "c-2", title: "Acme year end", current_version: 2, tags: [], updated_at: "2026-11-01T10:00:00+00:00" },
      ]);
      stub.route({ method: "GET", re: new RegExp(`/api/clients/${env.clientId}/knowledge\\?query=`), reply: () => ok([]) });
      await page.goto(env.at("/knowledge/"), { waitUntil: "networkidle" });
      await page.getByText("Acme quirks").waitFor();
      const search = page.getByLabel("Search client articles");
      await search.fill("zzz");
      await page.getByText("No article of this client has every word of \u201czzz\u201d in its title or its current text.").waitFor();
      await page.evaluate(() => {
        const w = /** @type {any} */ (window);
        w.__saidNone = false;
        const seen = () => { if (document.body.innerText.includes("No client-scoped articles.")) w.__saidNone = true; };
        new MutationObserver(seen).observe(document.body, { childList: true, subtree: true, characterData: true });
      });
      await search.fill("");
      await page.getByText("Acme quirks").waitFor();
      assert.equal(await page.evaluate(() => /** @type {any} */ (window).__saidNone), false,
        "the screen said the client has no articles while it had two");
    },
  },
  {
    id: "a-search-of-more-than-eight-words-shows-the-servers-refusal",
    title: "more than eight words: the server's sentence is shown",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: FIRM_SEARCH, ...refuse("A search takes at most 8 words; this one has 9.") });
      await atTheKnowledgeBase(env);
      await box(page).fill("a b c d e f g h i");
      await page.getByText("A search takes at most 8 words; this one has 9.").waitFor();
    },
  },
];
