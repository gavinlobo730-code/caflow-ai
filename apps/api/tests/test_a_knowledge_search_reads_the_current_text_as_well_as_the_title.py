"""A knowledge-base search reads each article's CURRENT text as well as its title (POST-A-216).

WHAT WAS WRONG
    `knowledge_service.search_articles` filtered `knowledge_articles` with `ilike` on the title and nothing else, although an
    article's words are its text, which lives one row per version in `knowledge_article_versions.content`. A CA who wrote
    "Form 15CA is filed before the remittance" under the title "Foreign payments" found nothing by searching "15CA". The read
    was also one unpaged request, so a firm past PostgREST's first thousand articles lost the rest without a word; and a typed
    `%` or `_` was a wildcard, so "50%" matched every article with "50" in it.

WHAT IT DOES NOW
    An article is found when EVERY word of the search is in its title or in its current text; one word may be in the title
    and another in the text.

WHAT THESE HOLD (mock mode, through the real service and routes over the shared in-memory database; the like pattern's
meaning on a real database is in the `_pg` file)
    * words in an article's current text find it, and the row says where they were found: "title", "text" or both;
    * every word must be found, in the title or the current text, in any order; a word repeated in another case is one word;
      more than eight words is a 422 in words;
    * words that were only in an OLD version, since edited out, do not find it; words added in the current version do; and it
      is the article's `current_version` that counts, not its newest version row (they differ when an edit wrote a version and
      failed to move the pointer);
    * the text match keeps every filter the title match has: the firm, the archived flag, the scope (a client's article is not
      in the firm list), one client's articles when asked, and the per-row visibility (an Executive does not reach an
      unassigned client's article through its text);
    * the match ignores case; blank words are the plain list, which carries no `matched_in`;
    * the list is last-updated first by instant (not by the stamp's text), ties in id order;
    * every row is read however many pages the reads take, against a double that, like PostgREST, answers at most a page to
      one request;
    * a typed backslash, `%` or `_` is escaped in the pattern. The in-memory database's `ilike` does not honour those escapes
      (it reads `\\%` as a backslash then anything), so what the pattern MEANS is held on real Postgres in the `_pg` file, and
      no test here searches for a `%` through the service.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import core.db_paging as paging
import tests.e2e_harness as harness
import services.knowledge_service as kb
from routers import knowledge as routes
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "F1", "F2"
MINE, THEIRS = "C-MINE", "C-THEIRS"


def _user(role="partner", uid="u1"):
    return {"id": uid, "firm_id": FIRM, "role": role}


@pytest.fixture()
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(kb, "_USE_MOCK", False)
    monkeypatch.setattr(kb, "_db", lambda: fake)
    monkeypatch.setattr(kb, "is_internal_client", lambda cid, fid: False)
    monkeypatch.setattr(kb, "is_assigned", lambda firm_id, user_id, client_id: client_id == MINE)
    return fake


def _article(db, title, *versions, scope="firm", client=None, firm=FIRM, archived=False, updated="2026-11-01T10:00:00+00:00",
             current=None, aid=None):
    """An article with its version rows; `versions` are the texts of versions 1..n, and the last is current unless `current` says."""
    row = {"firm_id": firm, "scope": scope, "client_id": client, "title": title, "is_archived": archived,
           "current_version": current or max(len(versions), 1), "updated_at": updated, "tags": []}
    if aid:
        row["id"] = aid
    art = db.seed("knowledge_articles", row)
    for n, text in enumerate(versions, start=1):
        db.seed("knowledge_article_versions", {"firm_id": firm, "article_id": art["id"], "version": n, "content": text})
    return art


def _found(rows):
    return {r["title"]: r.get("matched_in") for r in rows}


def test_words_in_the_current_text_find_the_article_and_the_row_says_where(db):
    _article(db, "Foreign payments", "Form 15CA is filed before the remittance.")
    _article(db, "Form 15CA checklist", "What to collect from the client.")
    _article(db, "15CA and 15CB together", "A 15CA in Part C needs a 15CB.")
    _article(db, "Leave policy", "Twelve days a year.")
    got = kb.search_articles(_user(), "15CA")
    assert _found(got) == {"Foreign payments": ["text"], "Form 15CA checklist": ["title"],
                           "15CA and 15CB together": ["title", "text"]}


def test_words_only_in_an_old_version_do_not_find_the_article_and_words_added_in_the_current_one_do(db):
    _article(db, "TDS on rent", "Rent is under 194-I.", "Rent is under 194-IB for individuals.")
    _article(db, "Advance tax", "Due on 15 June.", "Instalments: 15 June, 15 September, 15 December, 15 March.")
    assert _found(kb.search_articles(_user(), "194-IB")) == {"TDS on rent": ["text"]}
    assert kb.search_articles(_user(), "Due on 15 June") == []           # edited out of the current text
    assert _found(kb.search_articles(_user(), "15 March")) == {"Advance tax": ["text"]}


def test_every_word_must_be_found_in_the_title_or_the_current_text_in_any_order(db):
    _article(db, "Rent", "TDS is deducted above the threshold.")
    _article(db, "TDS basics", "Sections and rates.")
    _article(db, "Leases", "Rent is paid monthly; TDS under 194-I.")
    _article(db, "Rent agreements", "Stamp duty only.")
    for search in ("TDS rent", "rent TDS", "  rent   tds  ", "Rent rent TDS"):
        assert _found(kb.search_articles(_user(), search)) == {"Rent": ["title", "text"], "Leases": ["text"]}, search
    assert kb.search_articles(_user(), "TDS gratuity") == []


def test_more_than_eight_words_is_refused_in_words_and_eight_are_searched(db):
    _article(db, "Index", "p q r s t u v w")
    assert _found(kb.search_articles(_user(), "p q r s t u v w")) == {"Index": ["text"]}
    assert _found(kb.search_articles(_user(), "p q r s t u v w P")) == {"Index": ["text"]}      # P is p, once
    with pytest.raises(HTTPException) as exc:
        kb.search_articles(_user(), "p q r s t u v w y")
    assert exc.value.status_code == 422 and exc.value.detail == "A search takes at most 8 words; this one has 9."


def test_it_is_the_articles_current_version_that_counts_not_its_newest_version_row(db):
    _article(db, "Pointer behind", "old words here", "new words here", current=1)
    assert _found(kb.search_articles(_user(), "old")) == {"Pointer behind": ["text"]}
    assert kb.search_articles(_user(), "new") == []


def test_a_restored_old_text_is_found_because_a_restore_writes_it_as_the_current_version(db):
    art = _article(db, "GST on exports", "LUT is renewed every year.", "Exports pay IGST and claim a refund.",
                   "LUT is renewed every year.")
    assert [r["id"] for r in kb.search_articles(_user(), "LUT")] == [art["id"]]


def test_the_text_match_keeps_the_firm_the_archived_flag_and_the_scope(db):
    _article(db, "Another firm's note", "GSTR-9C reconciliation", firm=OTHER_FIRM)
    _article(db, "Archived note", "GSTR-9C reconciliation", archived=True)
    _article(db, "A client's note", "GSTR-9C reconciliation", scope="client", client=MINE)
    _article(db, "Department note", "GSTR-9C reconciliation", scope="department")
    assert _found(kb.search_articles(_user(), "gstr-9c")) == {"Department note": ["text"]}
    with_archived = kb.search_articles(_user(), "gstr-9c", None, None, True)
    assert _found(with_archived) == {"Department note": ["text"], "Archived note": ["text"]}
    assert _found(kb.search_articles(_user(), "gstr-9c", "client")) == {"A client's note": ["text"]}


def test_an_executive_does_not_reach_an_unassigned_clients_article_through_its_text(db):
    _article(db, "Acme quirks", "Their year closes in December.", scope="client", client=MINE)
    _article(db, "Beta quirks", "Their year closes in December too.", scope="client", client=THEIRS)
    assert _found(kb.search_articles(_user("executive"), "December", "client")) == {"Acme quirks": ["text"]}
    assert _found(kb.search_articles(_user("partner"), "December", "client")) == {
        "Acme quirks": ["text"], "Beta quirks": ["text"]}


def test_one_clients_search_reads_that_clients_articles_only_and_the_client_route_asks_the_same(db):
    _article(db, "Acme quirks", "Pays by cheque.", scope="client", client=MINE)
    _article(db, "Beta quirks", "Pays by cheque.", scope="client", client=THEIRS)
    _article(db, "Firm note", "Pays by cheque.")
    got = routes.client_knowledge(client_id=MINE, query="cheque", current_user=_user("executive"))["data"]
    assert _found(got) == {"Acme quirks": ["text"]}


def test_the_match_ignores_case_and_blank_words_are_the_plain_list_without_matched_in(db):
    _article(db, "Leave policy", "Casual leave is TWELVE days.", updated="2026-11-02T10:00:00+00:00")
    _article(db, "Holidays", "Gazetted holidays.", updated="2026-11-03T10:00:00+00:00")
    assert _found(kb.search_articles(_user(), "twelve")) == {"Leave policy": ["text"]}
    for blank in (None, "", "   "):
        rows = kb.search_articles(_user(), blank)
        assert [r["title"] for r in rows] == ["Holidays", "Leave policy"]
        assert all("matched_in" not in r for r in rows)


def test_the_list_is_last_updated_first_with_ties_in_id_order(db):
    _article(db, "B tie", "x", updated="2026-11-05T10:00:00+00:00", aid="id-b")
    _article(db, "A tie", "x", updated="2026-11-05T15:30:00+05:30", aid="id-a")      # the same instant written in IST
    _article(db, "Older by instant", "x", updated="2026-11-05T12:00:00+05:30", aid="id-z")   # 06:30 UTC; larger as text
    _article(db, "Oldest", "x", updated="2026-11-04T23:59:59.5+00:00", aid="id-0")
    _article(db, "No stamp", "x", updated=None, aid="id-n")
    expected = ["A tie", "B tie", "Older by instant", "Oldest", "No stamp"]
    assert [r["title"] for r in kb.search_articles(_user(), None)] == expected
    assert [r["title"] for r in kb.search_articles(_user(), "x")] == expected


def test_every_match_is_read_however_many_pages_the_reads_take(db, monkeypatch):
    monkeypatch.setattr(paging, "PAGE", 2)
    unpaged = harness._Query.execute

    def at_most_a_page(self):
        """Like PostgREST's db-max-rows: a read answers at most a page, whatever it asked for, and says nothing."""
        result = unpaged(self)
        if self._op == "select" and isinstance(result.data, list):
            result.data = result.data[:paging.PAGE]
        return result
    monkeypatch.setattr(harness._Query, "execute", at_most_a_page)
    for n in range(7):
        _article(db, f"Text {n}", f"Section 194J applies, case {n}.")
    for n in range(5):
        _article(db, f"Section 194J note {n}", "Nothing else.")
    _article(db, "Unrelated", "Section 192.")
    found = _found(kb.search_articles(_user(), "194J"))
    assert len(found) == 12 and "Unrelated" not in found
    assert len(kb.search_articles(_user(), None)) == 13


@pytest.mark.parametrize("words,pattern", [
    ("15CA", "%15CA%"),
    ("50%", "%50\\%%"),
    ("TDS_rate", "%TDS\\_rate%"),
    ("C:\\docs", "%C:\\\\docs%"),
    ("\\%_", "%\\\\\\%\\_%"),
])
def test_a_typed_backslash_percent_or_underscore_is_escaped_in_the_pattern(words, pattern):
    assert kb._like_pattern(words) == pattern


def test_the_firm_route_passes_the_words_and_the_scope_through(db):
    _article(db, "Foreign payments", "Form 15CA is filed before the remittance.", scope="department")
    got = routes.list_articles(query="15ca", scope="department", include_archived=False, current_user=_user())["data"]
    assert _found(got) == {"Foreign payments": ["text"]}
