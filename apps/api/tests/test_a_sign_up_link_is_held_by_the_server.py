"""A sign-up link is held by the server: it survives a second click and a mail scanner, and it carries what it was asked for (POST-A-485, 497).

WHAT WAS WRONG. A sign-up link was the sign-in library's own emailed one-time link. The first opener won, so a mail scanner that opens links
before the person does, a second click, or the link opened on a phone after the laptop left the person on a page that said it had expired
(POST-A-479 only softened the words). And what the link MEANT ("a new practice, not the one this address already belongs to") lived in a
note in the browser that sent the form, so a link opened in another browser entered an existing practice silently (POST-A-497).

WHAT IT DOES. The server keeps one row per address (the hash of the link's secret, the firm name and the person's name typed on the form,
the expiry) and mails the link itself; the page the link opens asks what the link is for (`look`), and a press asks for a sign-in for the
link's OWN address (`session`), which uses nothing up. The names come back with the sign-in, so the intent travels with the link.

These run on the REAL repository in mock mode (its store emptied before each test) and the real rules, so the hashing, the replacing
and the counters they hold are the code's, not a fake's. The mail service is the one double: it answers what each test says it did.

NEGATIVE CONTROLS (twelve breaks, each was run and each fails at least one test here)
    * the secret stored in the clear              - the hash and no-secret test
    * a press that uses the link up               - the survives-a-second-press test
    * an expired link that is live                - the expiry test
    * a failed mail that leaves its link          - the mail-failure test
    * the cooldown or the hourly cap removed      - the two refusal tests
    * asking that reads an account                - the mail-and-names test (the stand-in sign-in service is never called)
    * the names left out of the sign-in           - the names-travel test
    * creating the practice leaving the link      - the create-firm test
    * a link found by address and not by secret   - the replacing test
    * the mail not escaping what was typed        - the mail test
    * a window that never rolls over              - the window test
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import repositories.signup_link_repository as repo_module
import services.signup_link_service as svc
from core.urls import frontend_base
from domain.firm import signup_link as rules
from domain.firm.invite_token import stored_form
from middleware.public_rate_limit import reset as reset_public_limits
from repositories.signup_link_repository import signup_link_repo
from routers import signup as signup_router
from services import email_service, sign_in_link

NOW = datetime(2026, 11, 20, 9, 0, 0, tzinfo=timezone.utc)


def _at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


@pytest.fixture()
def world(monkeypatch):
    monkeypatch.setattr(repo_module, "_USE_MOCK", True)
    monkeypatch.setattr(svc, "_USE_MOCK", True)
    signup_link_repo.reset_mock()
    reset_public_limits()
    mails: list[dict] = []
    issued: list[str] = []

    def _issue():
        issued.append(f"tok-{len(issued) + 1:02d}-" + "z" * 36)
        return issued[-1]

    def _send(to, **kwargs):
        mails.append({"to": to, **kwargs})
        if world.raises:
            raise RuntimeError("the mail service fell over")
        return world.answer

    world = SimpleNamespace(mails=mails, issued=issued, answer=True, raises=False)
    monkeypatch.setattr(svc, "_new_token", _issue)
    monkeypatch.setattr(email_service, "send_signup_link", _send)
    yield world
    signup_link_repo.reset_mock()
    reset_public_limits()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(signup_router.router)
    return TestClient(app, raise_server_exceptions=False)


def _ask(email="ravi@sharma-co.in", firm="Sharma & Associates", name="CA Ravi Sharma", now=NOW):
    return svc.request_link(email, firm, name, now=now)


# ═══ THE RULES ════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_an_address_is_kept_trimmed_and_lower_case():
    assert rules.normalise_email("  Ravi@Sharma-Co.IN ") == "ravi@sharma-co.in"
    assert rules.normalise_email(None) == ""


def test_a_name_is_cleaned_not_rewritten():
    assert rules.clean_name("  Sharma &   Associates ", "your firm's name") == "Sharma & Associates"
    assert rules.clean_name("Zoë Müller-Ōkura", "your name") == "Zoë Müller-Ōkura"
    assert rules.clean_name("Line\r\nBreak\tName", "your name") == "Line Break Name", "controls and breaks cannot reshape a mail"
    assert rules.clean_name("<b>Not stripped</b>", "your name") == "<b>Not stripped</b>", "it is escaped where shown, never mangled here"


@pytest.mark.parametrize("value", ["", "   ", "\r\n\t", None])
def test_a_blank_name_is_refused_in_a_sentence(value):
    with pytest.raises(ValueError) as e:
        rules.clean_name(value, "your firm's name")
    assert str(e.value) == "Please enter your firm's name."


def test_a_name_that_is_too_long_is_refused_in_a_sentence():
    assert len(rules.clean_name("x" * rules.NAME_MAX, "your name")) == rules.NAME_MAX
    with pytest.raises(ValueError) as e:
        rules.clean_name("x" * (rules.NAME_MAX + 1), "your name")
    assert "Your name is too long" in str(e.value) and str(rules.NAME_MAX) in str(e.value)


def test_a_first_request_is_allowed_and_starts_the_count():
    a = rules.allowance(None, NOW)
    assert a.ok and a.send_count == 1 and a.window_started_at == NOW


def _row_sent_at(seconds_ago, count=1, window_ago=None):
    return {"sent_at": _at(-seconds_ago).isoformat(), "send_count": count,
            "window_started_at": _at(-(window_ago if window_ago is not None else seconds_ago)).isoformat()}


def test_a_second_request_inside_the_cooldown_is_refused_with_the_wait():
    a = rules.allowance(_row_sent_at(10), NOW)
    assert not a.ok and a.reason == "cooldown" and a.wait_seconds == rules.COOLDOWN_SECONDS - 10
    assert "wait 20 seconds" in rules.refusal_sentence(a)


def test_the_wait_is_never_below_one_second():
    a = rules.allowance(_row_sent_at(rules.COOLDOWN_SECONDS - 0.2), NOW)
    assert not a.ok and a.wait_seconds == 1
    assert "wait 1 second before" in rules.refusal_sentence(a)


def test_a_request_after_the_cooldown_is_allowed_and_counted():
    a = rules.allowance(_row_sent_at(rules.COOLDOWN_SECONDS + 1, count=2, window_ago=120), NOW)
    assert a.ok and a.send_count == 3
    assert a.window_started_at == _at(-120)


def test_the_hourly_cap_refuses_the_next_and_says_how_long():
    row = _row_sent_at(60, count=rules.HOURLY_CAP, window_ago=600)
    a = rules.allowance(row, NOW)
    assert not a.ok and a.reason == "hourly" and a.wait_seconds == 3000
    words = rules.refusal_sentence(a)
    assert f"{rules.HOURLY_CAP} times in the last hour" in words and "about 50 minutes" in words


def test_the_window_rolls_over_after_an_hour():
    a = rules.allowance(_row_sent_at(3700, count=rules.HOURLY_CAP, window_ago=3700), NOW)
    assert a.ok and a.send_count == 1 and a.window_started_at == NOW


@pytest.mark.parametrize("row", [{"sent_at": "garbage", "send_count": "x", "window_started_at": "never"},
                                 {"sent_at": None, "window_started_at": None}, {"unrelated": 1}])
def test_a_row_whose_stamps_cannot_be_read_is_a_first_request_not_a_lockout(row):
    a = rules.allowance(row, NOW)
    assert a.ok and a.send_count == 1


def test_a_link_is_live_only_before_its_expiry_and_an_unreadable_expiry_is_not_live():
    assert rules.is_live({"expires_at": _at(60).isoformat()}, NOW)
    assert not rules.is_live({"expires_at": _at(-1).isoformat()}, NOW)
    assert not rules.is_live({"expires_at": _at(0).isoformat()}, NOW), "an expiry that is exactly now has passed"
    assert not rules.is_live({"expires_at": "tomorrow-ish"}, NOW)
    assert not rules.is_live({}, NOW) and not rules.is_live(None, NOW)


def test_a_link_lives_twenty_four_hours():
    assert rules.expires_at(NOW) - NOW == timedelta(hours=24)


# ═══ ASKING FOR A LINK ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_asking_mails_one_link_to_the_address_typed_and_names_what_was_typed(world):
    asked = _ask()
    assert len(world.mails) == 1
    mail = world.mails[0]
    assert mail["to"] == "ravi@sharma-co.in"
    assert mail["firm_name"] == "Sharma & Associates" and mail["full_name"] == "CA Ravi Sharma"
    link = urlparse(mail["link"])
    assert mail["link"].startswith(f"{frontend_base()}/signup/continue/#token=")
    assert parse_qs(link.fragment)["token"] == [world.issued[0]], "the link carries the secret and nothing else"
    assert link.query == "" and link.path == "/signup/continue/", "a secret in a query or a path reaches the host's request log"
    assert mail["valid_until"] == asked.valid_until == "21 November 2026, 2:30 pm IST"
    assert asked.wait_seconds == rules.COOLDOWN_SECONDS


def test_only_the_secrets_hash_is_stored_and_the_secret_is_nowhere_in_the_row(world):
    _ask()
    row = signup_link_repo.find_by_email("ravi@sharma-co.in")
    assert row["token_hash"] == stored_form(world.issued[0]) and row["token_hash"].startswith("sha256:")
    assert world.issued[0] not in " ".join(str(v) for v in row.values())


def test_the_row_carries_the_names_the_expiry_and_the_counters(world):
    _ask()
    row = signup_link_repo.find_by_email("ravi@sharma-co.in")
    assert (row["firm_name"], row["full_name"]) == ("Sharma & Associates", "CA Ravi Sharma")
    assert row["expires_at"] == _at(24 * 3600).isoformat()
    assert row["send_count"] == 1 and row["sent_at"] == NOW.isoformat() and row["window_started_at"] == NOW.isoformat()


def test_an_address_is_matched_whatever_its_case_so_there_is_one_row(world):
    _ask(email="Ravi@Sharma-Co.in")
    _ask(email="  ravi@sharma-co.IN ", now=_at(rules.COOLDOWN_SECONDS + 1))
    assert world.mails[0]["to"] == world.mails[1]["to"] == "ravi@sharma-co.in"
    assert len(repo_module._MOCK_ROWS) == 1


def test_asking_again_replaces_the_link_and_the_earlier_one_stops_working(world, monkeypatch):
    _ask()
    monkeypatch.setattr(svc, "_now", lambda: _at(rules.COOLDOWN_SECONDS + 5))
    first = world.issued[0]
    assert svc.look(first)["email"] == "ravi@sharma-co.in"
    _ask(now=_at(rules.COOLDOWN_SECONDS + 1))
    second = world.issued[1]
    assert first != second
    assert svc.look(second)["email"] == "ravi@sharma-co.in"
    with pytest.raises(Exception) as gone:
        svc.look(first)
    assert gone.value.status_code == 404 and gone.value.detail == svc.NOT_ACTIVE
    assert signup_link_repo.find_by_email("ravi@sharma-co.in")["send_count"] == 2


def test_a_request_inside_the_cooldown_is_refused_with_the_wait_and_mails_nothing(world):
    _ask()
    with pytest.raises(svc.LinkRefused) as refused:
        _ask(now=_at(10))
    assert refused.value.status_code == 429 and refused.value.wait_seconds == rules.COOLDOWN_SECONDS - 10
    assert refused.value.headers["Retry-After"] == str(rules.COOLDOWN_SECONDS - 10)
    assert "wait 20 seconds" in refused.value.detail
    assert len(world.mails) == 1, "a refused request must not send a mail"
    assert world.issued == [world.issued[0]], "...nor mint a token"


def test_the_sixth_request_in_an_hour_is_refused_and_the_first_five_are_not(world):
    for n in range(rules.HOURLY_CAP):
        _ask(now=_at(n * 60))
    assert len(world.mails) == rules.HOURLY_CAP
    with pytest.raises(svc.LinkRefused) as refused:
        _ask(now=_at(rules.HOURLY_CAP * 60))
    assert "5 times in the last hour" in refused.value.detail
    assert len(world.mails) == rules.HOURLY_CAP
    _ask(now=_at(3601 + 60))             # the window has rolled over
    assert len(world.mails) == rules.HOURLY_CAP + 1


def test_one_address_being_asked_for_does_not_spend_another_addresses_allowance(world):
    _ask(email="a@x.in")
    _ask(email="b@x.in", now=_at(1))
    assert len(world.mails) == 2


@pytest.mark.parametrize("firm, name, words", [("", "N", "your firm's name"), ("F", "  ", "your name")])
def test_a_blank_name_is_a_value_error_and_nothing_is_stored_or_sent(world, firm, name, words):
    with pytest.raises(ValueError) as e:
        _ask(firm=firm, name=name)
    assert words in str(e.value)
    assert world.mails == [] and repo_module._MOCK_ROWS == {}


def test_a_mail_that_did_not_go_is_a_503_in_words_and_leaves_no_link_behind(world):
    world.answer = False
    with pytest.raises(Exception) as e:
        _ask()
    assert e.value.status_code == 503 and e.value.detail == svc.MAIL_NOT_SENT
    assert repo_module._MOCK_ROWS == {}, "a link nobody was mailed must not be a link that works"


def test_a_mail_that_raised_is_the_same_503(world):
    world.raises = True
    with pytest.raises(Exception) as e:
        _ask()
    assert e.value.status_code == 503 and e.value.detail == svc.MAIL_NOT_SENT
    assert repo_module._MOCK_ROWS == {}


def test_a_resend_whose_mail_did_not_go_puts_the_earlier_link_back(world, monkeypatch):
    _ask()
    monkeypatch.setattr(svc, "_now", lambda: _at(rules.COOLDOWN_SECONDS + 5))
    first = world.issued[0]
    world.answer = False
    with pytest.raises(HTTPException):
        _ask(now=_at(rules.COOLDOWN_SECONDS + 1))
    assert svc.look(first)["email"] == "ravi@sharma-co.in", "the person's earlier mail must keep working"
    row = signup_link_repo.find_by_email("ravi@sharma-co.in")
    assert row["send_count"] == 1 and row["token_hash"] == stored_form(first)


def test_a_put_back_never_undoes_a_newer_request(world):
    _ask()
    previous = signup_link_repo.find_by_email("ravi@sharma-co.in")
    assert signup_link_repo.put_back("ravi@sharma-co.in", previous, replacing="sha256:not-the-current-one") is False
    assert signup_link_repo.find_by_email("ravi@sharma-co.in")["token_hash"] == stored_form(world.issued[0])


def test_asking_reads_no_account_so_an_existing_address_cannot_be_told_from_a_new_one(world, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("asking for a link touched the sign-in service")
    monkeypatch.setattr(sign_in_link, "mint", _boom)
    monkeypatch.setattr(svc.db_provider, "service_db", _boom)
    _ask(email="has.an.account@x.in")
    _ask(email="brand.new@x.in", now=_at(1))
    assert len(world.mails) == 2


def _seed(email, expires_in_seconds):
    signup_link_repo.save({"email": email, "firm_name": "F", "full_name": "N", "token_hash": stored_form(email),
                           "expires_at": _at(expires_in_seconds), "sent_at": _at(-10 ** 6), "send_count": 1,
                           "window_started_at": _at(-10 ** 6), "created_at": _at(-10 ** 6)})


def test_links_that_have_expired_are_swept_by_the_next_request_and_live_ones_are_not(world):
    _seed("long-gone@x.in", -2 * 24 * 3600)            # expired two days ago
    _seed("just-expired@x.in", -60)                    # expired a minute ago: nothing reads an expired row, and the page says the same for it as for an unknown one
    _seed("still-live@x.in", 3600)
    assert set(repo_module._MOCK_ROWS) == {"long-gone@x.in", "just-expired@x.in", "still-live@x.in"}
    _ask(email="new@x.in", now=NOW)
    assert set(repo_module._MOCK_ROWS) == {"still-live@x.in", "new@x.in"}


def test_the_daily_sweeps_close_removes_the_expired_links_for_no_firm(world, monkeypatch):
    """No firm owns a link nobody used, so the one place that runs for every deployment once a day is the sweep's close."""
    import jobs.scheduler as scheduler
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    _seed("long-gone@x.in", -2 * 24 * 3600)
    _seed("just-expired@x.in", -60)
    _seed("still-live@x.in", 3600)
    scheduler._close_sweep([])
    assert set(repo_module._MOCK_ROWS) == {"still-live@x.in"}


def test_sweeping_never_raises_so_it_cannot_end_a_sweep_or_refuse_a_request(world, monkeypatch):
    import jobs.scheduler as scheduler

    def _fails(cutoff):
        raise RuntimeError("the store is down")
    monkeypatch.setattr(signup_link_repo, "delete_expired_before", _fails)
    svc.sweep_expired()
    scheduler._close_sweep([])


def test_a_sweep_that_fails_does_not_stop_a_person_asking(world, monkeypatch):
    def _fails(cutoff):
        raise RuntimeError("the sweep failed")
    monkeypatch.setattr(signup_link_repo, "delete_expired_before", _fails)
    _ask()
    assert len(world.mails) == 1


# ═══ LOOKING AT A LINK, AND PRESSING IT ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def asked(world, monkeypatch):
    monkeypatch.setattr(svc, "_now", lambda: _at(60))
    _ask()
    return world.issued[0]


def test_looking_says_what_the_link_is_for_and_signs_nobody_in(asked, monkeypatch):
    monkeypatch.setattr(svc.db_provider, "service_db", lambda: pytest.fail("looking opened a sign-in"))
    seen = svc.look(asked)
    assert seen["email"] == "ravi@sharma-co.in"
    assert (seen["firm_name"], seen["full_name"]) == ("Sharma & Associates", "CA Ravi Sharma")
    assert seen["valid_until"] == "21 November 2026, 2:30 pm IST"


def test_a_press_opens_a_sign_in_for_the_links_own_address_with_the_names_it_was_asked_for(asked):
    opened = svc.open_sign_in(asked)
    assert opened["email"] == "ravi@sharma-co.in"
    assert (opened["firm_name"], opened["full_name"]) == ("Sharma & Associates", "CA Ravi Sharma"), "the intent travels with the link (POST-A-497)"
    assert opened["token_hash"].startswith("mock-signup-link-") and opened["verification_type"] == "magiclink"


def test_a_second_press_signs_in_again_because_nothing_is_used_up(asked):
    first = svc.open_sign_in(asked)
    second = svc.open_sign_in(asked)
    assert first == second
    assert svc.look(asked)["email"] == "ravi@sharma-co.in", "the link still stands after two presses"


def test_a_scanner_that_looks_first_spends_nothing(asked):
    for _ in range(5):
        svc.look(asked)
    assert svc.open_sign_in(asked)["email"] == "ravi@sharma-co.in"


@pytest.mark.parametrize("call", [svc.look, svc.open_sign_in])
@pytest.mark.parametrize("token", ["", "no-such-token", None, 12345, "x" * 400])
def test_every_link_that_cannot_be_used_gets_the_one_404(asked, call, token):
    with pytest.raises(Exception) as e:
        call(token)
    assert e.value.status_code == 404 and e.value.detail == svc.NOT_ACTIVE


@pytest.mark.parametrize("call", [svc.look, svc.open_sign_in])
def test_a_stored_hash_is_never_taken_for_the_secret(asked, call):
    with pytest.raises(Exception) as e:
        call(stored_form(asked))
    assert e.value.status_code == 404


@pytest.mark.parametrize("call", [svc.look, svc.open_sign_in])
def test_a_link_past_its_expiry_cannot_be_looked_at_or_pressed(asked, monkeypatch, call):
    monkeypatch.setattr(svc, "_now", lambda: _at(24 * 3600 + 61))
    with pytest.raises(Exception) as e:
        call(asked)
    assert e.value.status_code == 404 and e.value.detail == svc.NOT_ACTIVE


def test_a_link_one_second_before_its_expiry_still_works(asked, monkeypatch):
    monkeypatch.setattr(svc, "_now", lambda: _at(24 * 3600 - 1))
    assert svc.look(asked)["email"] == "ravi@sharma-co.in"


def test_the_practice_being_created_ends_the_link(asked):
    svc.forget("Ravi@Sharma-Co.IN")
    for call in (svc.look, svc.open_sign_in):
        with pytest.raises(Exception) as e:
            call(asked)
        assert e.value.status_code == 404


def test_forgetting_an_address_with_no_link_or_no_address_is_quiet(world):
    svc.forget("nobody@x.in")
    svc.forget(None)
    svc.forget("")


def test_forgetting_never_raises_even_when_the_store_does(asked, monkeypatch):
    monkeypatch.setattr(signup_link_repo, "delete_by_email", lambda e: (_ for _ in ()).throw(RuntimeError("down")))
    svc.forget("ravi@sharma-co.in")


class _Admin:
    """The sign-in service's administrator calls, answering what each test says an address is."""
    def __init__(self, existing=False, fails=False):
        self.existing, self.fails, self.calls = existing, fails, []

    def generate_link(self, params):
        self.calls.append(params)
        if self.fails:
            raise RuntimeError("the sign-in service is down")
        if params["type"] == "invite" and self.existing:
            raise RuntimeError("A user with this email address has already been registered")
        return SimpleNamespace(properties=SimpleNamespace(hashed_token=f"hash-{params['type']}", verification_type=params["type"]))


def _real(monkeypatch, admin):
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc.db_provider, "service_db", lambda: SimpleNamespace(auth=SimpleNamespace(admin=admin)))


def test_a_new_address_is_given_an_invite_sign_in_for_its_own_address_only(asked, monkeypatch):
    admin = _Admin()
    _real(monkeypatch, admin)
    opened = svc.open_sign_in(asked)
    assert admin.calls == [{"type": "invite", "email": "ravi@sharma-co.in"}]
    assert opened["token_hash"] == "hash-invite" and opened["verification_type"] == "invite" and opened["email"] == "ravi@sharma-co.in"


def test_an_address_that_already_has_a_sign_in_is_signed_in_as_before_not_refused(asked, monkeypatch):
    """Unlike a staff invitation, whose holder could be somebody it was forwarded to: this link goes only to the mailbox of the address it
    opens, which is the proof the library's emailed link was. The wizard then says the address already has a practice (POST-A-480)."""
    admin = _Admin(existing=True)
    _real(monkeypatch, admin)
    opened = svc.open_sign_in(asked)
    assert [c["type"] for c in admin.calls] == ["invite", "magiclink"]
    assert all(c["email"] == "ravi@sharma-co.in" for c in admin.calls)
    assert opened["token_hash"] == "hash-magiclink"


def test_a_sign_in_service_that_cannot_mint_is_a_503_in_words_and_the_link_stands(asked, monkeypatch):
    _real(monkeypatch, _Admin(fails=True))
    with pytest.raises(Exception) as e:
        svc.open_sign_in(asked)
    assert e.value.status_code == 503 and e.value.detail == svc.SIGN_IN_REFUSAL
    monkeypatch.setattr(svc, "_USE_MOCK", True)
    assert svc.open_sign_in(asked)["email"] == "ravi@sharma-co.in", "a failure to mint spends nothing"


# ═══ THE THREE ROUTES ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_the_route_asks_mails_and_says_what_the_page_needs_to_say(world):
    r = _client().post("/api/signup/link", json={"email": "Ravi@Sharma-Co.in", "firm_name": "Sharma & Associates", "full_name": "CA Ravi Sharma"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["error"] is None
    assert set(body["data"]) == {"sent", "valid_until", "wait_seconds"} and body["data"]["sent"] is True
    assert body["data"]["wait_seconds"] == rules.COOLDOWN_SECONDS
    assert len(world.mails) == 1 and world.mails[0]["to"] == "ravi@sharma-co.in"


def test_the_routes_answer_carries_neither_the_secret_nor_its_hash(world):
    r = _client().post("/api/signup/link", json={"email": "ravi@sharma-co.in", "firm_name": "F", "full_name": "N"})
    assert world.issued[0] not in r.text and "sha256" not in r.text and stored_form(world.issued[0]) not in r.text


def test_the_route_refuses_a_blank_name_in_a_sentence(world):
    r = _client().post("/api/signup/link", json={"email": "ravi@sharma-co.in", "firm_name": "   ", "full_name": "N"})
    assert r.status_code == 422 and r.json()["detail"] == "Please enter your firm's name."


def test_the_route_refuses_what_is_not_an_address(world):
    r = _client().post("/api/signup/link", json={"email": "not-an-address", "firm_name": "F", "full_name": "N"})
    assert r.status_code == 422
    assert world.mails == []


def test_a_repeat_inside_the_cooldown_is_a_429_with_retry_after_on_the_route(world, monkeypatch):
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    body = {"email": "ravi@sharma-co.in", "firm_name": "F", "full_name": "N"}
    assert _client().post("/api/signup/link", json=body).status_code == 200
    r = _client().post("/api/signup/link", json=body)
    assert r.status_code == 429
    assert 1 <= int(r.headers["retry-after"]) <= rules.COOLDOWN_SECONDS
    assert "wait" in r.json()["detail"]
    assert len(world.mails) == 1


def test_a_failed_mail_is_a_503_on_the_route(world):
    world.answer = False
    r = _client().post("/api/signup/link", json={"email": "ravi@sharma-co.in", "firm_name": "F", "full_name": "N"})
    assert r.status_code == 503 and r.json()["detail"] == svc.MAIL_NOT_SENT


def test_looking_and_pressing_through_the_routes(world, monkeypatch):
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    c = _client()
    c.post("/api/signup/link", json={"email": "ravi@sharma-co.in", "firm_name": "Sharma & Associates", "full_name": "CA Ravi Sharma"})
    token = world.issued[0]
    looked = c.post("/api/signup/link/look", json={"token": token})
    assert looked.status_code == 200 and looked.json()["data"]["firm_name"] == "Sharma & Associates"
    pressed = c.post("/api/signup/link/session", json={"token": token})
    assert pressed.status_code == 200 and pressed.json()["data"]["email"] == "ravi@sharma-co.in"
    again = c.post("/api/signup/link/session", json={"token": token})
    assert again.status_code == 200, "a second press is not refused"
    refused = c.post("/api/signup/link/session", json={"token": "wrong"})
    assert refused.status_code == 404 and refused.json()["detail"] == svc.NOT_ACTIVE


def test_the_secret_is_in_a_body_and_never_in_a_path_or_a_query():
    paths = [r.path for r in signup_router.router.routes]
    assert sorted(paths) == ["/api/signup/link", "/api/signup/link/look", "/api/signup/link/session"]
    assert not any("{" in p for p in paths), "a path parameter would put the secret in every access log"


def test_the_three_routes_are_public_and_carry_a_per_address_limit():
    buckets = {}
    for route in signup_router.router.routes:
        calls = [d.call for d in route.dependant.dependencies]
        buckets[route.path] = [getattr(c, "_public_limit_bucket", None) for c in calls]
    assert buckets == {"/api/signup/link": ["signup"], "/api/signup/link/look": ["invite"], "/api/signup/link/session": ["invite"]}


# ═══ THE MAIL ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def sent(monkeypatch):
    out: list[dict] = []
    monkeypatch.setattr(email_service, "_send", lambda to, subject, html, **kw: out.append({"to": to, "subject": subject, "html": html, **kw}) or True)
    return out


def test_the_mail_says_what_it_is_for_when_it_ends_and_that_it_is_safe_to_ignore(sent):
    ok = email_service.send_signup_link("ravi@sharma-co.in", firm_name="Sharma & Associates", full_name="CA Ravi Sharma",
                                        link="https://app.example/signup/continue?token=abc", valid_until="21 November 2026, 2:30 pm IST")
    assert ok is True
    mail = sent[0]
    assert mail["subject"] == "Finish setting up Sharma & Associates on PracticeSync AI"
    html = mail["html"]
    assert "Sharma &amp; Associates" in html and "CA Ravi Sharma" in html
    assert 'href="https://app.example/signup/continue?token=abc"' in html
    assert "21 November 2026, 2:30 pm IST" in html and "ignore this email" in html and "whichever is first" in html


def test_the_mail_is_sent_as_the_product_with_nobody_to_reply_to(sent):
    email_service.send_signup_link("a@x.in", firm_name="F", full_name="N", link="https://l", valid_until="v")
    assert sent[0].get("sender_name") is None and sent[0].get("reply_to") is None


def test_typed_text_cannot_inject_markup_or_a_header(sent):
    email_service.send_signup_link("a@x.in", firm_name='<img src=x onerror=alert(1)>\r\nBcc: evil@x.in', full_name="<script>x</script>",
                                   link="https://l/?a=1&b=2", valid_until="v")
    mail = sent[0]
    assert "<script>" not in mail["html"] and "<img" not in mail["html"]
    assert "&lt;script&gt;" in mail["html"] and "&amp;b=2" in mail["html"]
    assert "\r" not in mail["subject"] and "\n" not in mail["subject"], "a typed name cannot add a header"


# ═══ CREATING THE PRACTICE ENDS THE LINK ═══════════════════════════════════════════════════════════════════════════════════════════════

class _Table:
    def __init__(self, db, name):
        self.db, self.name, self._insert = db, name, None

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def insert(self, row): self._insert = row; return self

    def execute(self):
        if self._insert is None:
            return SimpleNamespace(data=[])
        if self.db.fail_on == self.name:
            raise RuntimeError(f"insert into {self.name} failed")
        return SimpleNamespace(data=[{"id": f"{self.name}-1", **self._insert}])


class _FirmDB:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on

    def table(self, name):
        return _Table(self, name)


def _create_firm(monkeypatch, db, email="ravi@sharma-co.in"):
    import routers.onboarding as onboarding
    import services.coa_seed_service as coa
    import services.internal_client_service as ics
    monkeypatch.setattr(onboarding, "get_service_supabase", lambda: db)
    monkeypatch.setattr(coa, "seed_firm_coa", lambda *a, **k: None)
    monkeypatch.setattr(ics, "provision", lambda *a, **k: "PRACTICE-NEW")
    body = onboarding.FirmCreate(firm_name="Sharma & Associates", firm_email="firm@sharma-co.in", partner_name="CA Ravi Sharma")
    return onboarding.create_firm(body, jwt_user={"auth_user_id": "auth-ravi", "email": email})


def test_creating_the_practice_removes_the_link_it_was_made_from_and_only_that_one(world, monkeypatch):
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    _ask(email="ravi@sharma-co.in")
    _ask(email="someone.else@x.in", now=_at(1))
    mine = world.issued[0]
    assert svc.look(mine)["email"] == "ravi@sharma-co.in"
    assert _create_firm(monkeypatch, _FirmDB())["success"] is True
    with pytest.raises(Exception) as e:
        svc.look(mine)
    assert e.value.status_code == 404, "the mail must not sign anybody in once the practice exists"
    assert svc.look(world.issued[1])["email"] == "someone.else@x.in", "another person's link is not this firm's business"


def test_the_address_is_the_signed_in_ones_whatever_case_it_carries(world, monkeypatch):
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    _ask(email="ravi@sharma-co.in")
    _create_firm(monkeypatch, _FirmDB(), email="Ravi@Sharma-Co.IN")
    assert repo_module._MOCK_ROWS == {}


def test_a_practice_that_could_not_be_created_keeps_the_link_so_the_person_can_try_again(world, monkeypatch):
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    _ask(email="ravi@sharma-co.in")
    with pytest.raises(RuntimeError):
        _create_firm(monkeypatch, _FirmDB(fail_on="firms"))
    assert svc.look(world.issued[0])["email"] == "ravi@sharma-co.in"


def test_a_link_that_cannot_be_removed_does_not_fail_the_practice(world, monkeypatch):
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    _ask(email="ravi@sharma-co.in")
    monkeypatch.setattr(signup_link_repo, "delete_by_email", lambda e: (_ for _ in ()).throw(RuntimeError("down")))
    assert _create_firm(monkeypatch, _FirmDB())["success"] is True


# ═══ THE SERVER AND THE BROWSER AGREE ═════════════════════════════════════════════════════════════════════════════════════════════════════

def test_the_link_in_the_mail_opens_a_page_that_exists_and_the_browser_knows_the_servers_dead_link_sentence():
    """Written from the side that owns the vocabulary: the web test cannot see this module, so a drift in either sentence or path would pass
    both suites. The mail points at /signup/continue; that page must exist; and the pattern the page uses to tell a dead link from a failure
    must match the one sentence the server answers for every link that cannot be used (and neither of its other two)."""
    import pathlib
    import re
    web = pathlib.Path(svc.__file__).resolve().parents[2] / "web"
    assert urlparse(svc.continue_url("t")).path == "/signup/continue/"
    assert (web / "app" / "signup" / "continue" / "page.tsx").is_file()
    source = (web / "lib" / "auth" / "signupContinue.ts").read_text(encoding="utf-8")
    found = re.search(r"export const LINK_NOT_ACTIVE = /(.+?)/(i?);", source)
    assert found, "the browser's pattern for the server's sentence was not found"
    pattern = re.compile(found.group(1), re.I if found.group(2) else 0)
    assert pattern.search(svc.NOT_ACTIVE)
    assert not pattern.search(svc.MAIL_NOT_SENT) and not pattern.search(svc.SIGN_IN_REFUSAL)


def test_the_public_prefix_list_covers_the_page_the_mail_links_to():
    """/signup is a public prefix, so /signup/continue needs no session to open (the link is for a person who has none)."""
    import pathlib
    web = pathlib.Path(svc.__file__).resolve().parents[2] / "web"
    source = (web / "lib" / "auth" / "public-paths.ts").read_text(encoding="utf-8")
    assert '"/signup",' in source


# ═══ ONE WRITER, ONE ENDING ════════════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_only_the_service_uses_the_repository_and_only_the_create_firm_route_ends_a_link():
    import pathlib
    api = pathlib.Path(svc.__file__).resolve().parents[1]
    uses_repo, ends = [], []
    for path in api.glob("**/*.py"):
        rel = path.relative_to(api).as_posix()
        if rel.startswith(("tests/", "migrations/", "scripts/")):
            continue
        text = path.read_text(encoding="utf-8")
        if "signup_link_repo" in text or "signup_link_repository" in text:
            uses_repo.append(rel)
        if "signup_link_service.forget" in text:
            ends.append(rel)
    assert sorted(uses_repo) == ["repositories/signup_link_repository.py", "services/signup_link_service.py"], uses_repo
    assert ends == ["routers/onboarding.py"], ends
