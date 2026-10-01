"""A login token must be issued for THIS product, not merely be genuine.

SECURITY-PRIVACY-21

WHAT WAS WRONG
    `jwt.decode(..., options={"verify_aud": False})` with no issuer check, in two
    places. So any token signed by the project's keys was accepted as long as it
    carried a `sub` — a token minted for some other audience, or for some other
    purpose the same project signs — and the impact was bounded only by portal and
    employee tokens having no users row, which is not a control anybody designed.
    And `sessions_revoked_at` (the forced-logout instant) was compared inside
    `except Exception: pass`, so a value the code could not read let the very
    token the account's owner had revoked straight through, with a 200.

HOW THESE ARE WRITTEN
    Nearly every other test in this suite monkeypatches `jwt.decode`, which is why
    nothing ever noticed: a stub ignores the audience it is handed. These sign REAL
    ES256 tokens (what a Supabase project issues) with a generated key, and let the
    real PyJWT verify them against a fake JWKS that returns the matching public
    key. Only the JWKS fetch and the users lookup are doubled.

    Claim shapes are Supabase's: a user access token carries
    aud="authenticated", iss="<SUPABASE_URL>/auth/v1", sub, exp, iat, role, aal
    and session_id; the anon and service_role API keys carry iss="supabase", a
    role, iat and exp, and NO sub and NO aud.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

import core.auth as auth

API_ROOT = Path(__file__).resolve().parents[1]
SUPABASE_URL = "https://abcdefghijklmnop.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
DELETE = object()

_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())
_OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


class _Signing:
    key = _SIGNING_KEY.public_key()


class _Jwks:
    def get_signing_key_from_jwt(self, _token):
        return _Signing()


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return _Res(self._data)


class _Supabase:
    def __init__(self, user_row):
        self._rows = {
            "users": user_row,
            "firms": {"is_active": True, "deleted_at": None},
            "user_permissions": [],
        }

    def table(self, name):
        assert name in self._rows, f"the auth path queried {name!r}"
        return _Q(self._rows[name])


USER_ROW = {"id": "u1", "firm_id": "F1", "role": "Partner", "is_active": True}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.delenv("SUPABASE_JWT_ISSUER", raising=False)
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: _Jwks())
    monkeypatch.setattr(auth, "_user_lookup_cache", {})

    def install(user_row=None):
        row = dict(USER_ROW if user_row is None else user_row)
        monkeypatch.setattr(auth, "get_service_supabase", lambda: _Supabase(row))
        monkeypatch.setattr(auth, "_user_lookup_cache", {})

    install()
    return install


def _claims(**over):
    now = int(time.time())
    claims = {
        "iss": ISSUER, "aud": "authenticated", "sub": "auth-user-1",
        "email": "partner@firm.in", "role": "authenticated", "aal": "aal1",
        "session_id": "5e9b5a5e-0000-4000-8000-000000000001",
        "iat": now, "exp": now + 3600,
    }
    for k, v in over.items():
        if v is DELETE:
            claims.pop(k, None)
        else:
            claims[k] = v
    return claims


def _token(key=None, **over) -> str:
    return jwt.encode(_claims(**over), key or _SIGNING_KEY, algorithm="ES256",
                      headers={"kid": "test-key-1"})


def _bearer(token: str) -> str:
    return f"Bearer {token}"


def _staff(token: str):
    return auth.get_current_user(authorization=_bearer(token))


def _lightweight(token: str):
    return auth.get_jwt_user(authorization=_bearer(token))


DOORS = [pytest.param(_staff, id="get_current_user"),
         pytest.param(_lightweight, id="get_jwt_user")]


def _refused(door, token, *, status=401):
    with pytest.raises(HTTPException) as ei:
        door(token)
    assert ei.value.status_code == status, (ei.value.status_code, ei.value.detail)
    return ei.value.detail


# ── a correct token still works, on both doors ───────────────────────────────

def test_a_real_user_token_is_accepted(world):
    user = _staff(_token())
    assert user["auth_user_id"] == "auth-user-1"
    assert user["firm_id"] == "F1" and user["role"] == "Partner"
    assert user["aal"] == "aal1"


def test_the_lightweight_door_accepts_one_too(world):
    assert _lightweight(_token(aal="aal2")) == {
        "auth_user_id": "auth-user-1", "email": "partner@firm.in", "aal": "aal2"}


def test_a_trailing_slash_on_the_project_url_does_not_break_the_issuer(world, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL + "/")
    assert _staff(_token())["firm_id"] == "F1"


# ── audience ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("aud", ["service_role", "anon", "some-other-product",
                                 ["other", "another"], ""])
def test_a_token_for_another_audience_is_refused(world, door, aud):
    _refused(door, _token(aud=aud))


@pytest.mark.parametrize("door", DOORS)
def test_a_token_with_no_audience_is_refused(world, door):
    _refused(door, _token(aud=DELETE))


# ── issuer ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("iss", [
    "https://someone-elses-project.supabase.co/auth/v1",
    "supabase",
    SUPABASE_URL,                      # the origin without the /auth/v1 path
    SUPABASE_URL + "/auth/v1/",        # close, and not the same string
    "",
])
def test_a_token_from_another_issuer_is_refused(world, door, iss):
    _refused(door, _token(iss=iss))


@pytest.mark.parametrize("door", DOORS)
def test_a_token_with_no_issuer_is_refused(world, door):
    _refused(door, _token(iss=DELETE))


def test_a_custom_domain_can_name_its_own_issuer_and_only_that_one(world, monkeypatch):
    custom = "https://auth.practice.example/auth/v1"
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", custom + "/")
    assert _staff(_token(iss=custom))["firm_id"] == "F1"
    # An override REPLACES the derived issuer; it is one exact string, not a list.
    _refused(_staff, _token(iss=ISSUER))


# ── required claims ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("claim", ["iat", "exp", "sub"])
def test_a_token_missing_a_required_claim_is_refused(world, door, claim):
    detail = _refused(door, _token(**{claim: DELETE}))
    assert claim in detail, detail


def test_an_empty_subject_is_still_refused(world):
    _refused(_staff, _token(sub=""))


def test_the_service_role_key_is_not_a_login(world):
    """What `SUPABASE_SERVICE_ROLE_KEY` decodes to: signed by the project,
    iss "supabase", a role, iat and exp — no sub, no aud."""
    now = int(time.time())
    key_shaped = jwt.encode(
        {"iss": "supabase", "ref": "abcdefghijklmnop", "role": "service_role",
         "iat": now, "exp": now + 10 * 365 * 86400},
        _SIGNING_KEY, algorithm="ES256", headers={"kid": "test-key-1"})
    for door in (_staff, _lightweight):
        _refused(door, key_shaped)


# ── what was already refused stays refused ───────────────────────────────────

@pytest.mark.parametrize("door", DOORS)
def test_an_expired_token_is_still_refused(world, door):
    assert "expired" in _refused(door, _token(iat=int(time.time()) - 7200,
                                              exp=int(time.time()) - 3600)).lower()


@pytest.mark.parametrize("door", DOORS)
def test_a_token_signed_by_another_key_is_still_refused(world, door):
    _refused(door, _token(key=_OTHER_KEY))


@pytest.mark.parametrize("door", DOORS)
def test_no_bearer_header_is_still_refused(world, door):
    with pytest.raises(HTTPException) as ei:
        if door is _staff:
            auth.get_current_user(authorization=None)
        else:
            auth.get_jwt_user(authorization=None)
    assert ei.value.status_code == 401


# ── session revocation ───────────────────────────────────────────────────────

def _with_revocation(world, value):
    world({**USER_ROW, "sessions_revoked_at": value})


@pytest.mark.parametrize("garbled", [
    "not-a-date", "31/12/2026", "2026-13-45T99:99:99+00:00", "yesterday", "0000",
    "null", "🙂",
])
def test_an_unreadable_revocation_refuses_rather_than_passes(world, garbled):
    _with_revocation(world, garbled)
    detail = _refused(_staff, _token())
    assert "could not be verified" in detail


def test_a_revocation_after_the_token_was_issued_refuses(world):
    now = int(time.time())
    _with_revocation(world, datetime.fromtimestamp(now + 60, timezone.utc).isoformat())
    assert "revoked" in _refused(_staff, _token(iat=now)).lower()


def test_a_revocation_before_the_token_was_issued_lets_it_through(world):
    now = int(time.time())
    _with_revocation(world, datetime.fromtimestamp(now - 3600, timezone.utc).isoformat())
    assert _staff(_token(iat=now))["role"] == "Partner"


@pytest.mark.parametrize("stamp", [
    # What PostgREST sends for a timestamptz: microseconds trimmed of trailing
    # zeros, so five digits is ordinary, and an offset rather than a Z.
    "2020-01-01T10:00:00.12345+00:00",
    "2020-01-01T10:00:00+00:00",
    "2020-01-01T10:00:00.123456+05:30",
    "2020-01-01T10:00:00Z",
    "2020-01-01 10:00:00+00",
])
def test_every_timestamp_shape_postgrest_sends_still_parses(world, stamp):
    """Failing closed makes a format the parser cannot read an outage for that
    user, so the formats that really arrive are pinned here."""
    _with_revocation(world, stamp)
    assert _staff(_token())["role"] == "Partner"


def test_a_naive_revocation_is_read_as_utc_not_as_the_hosts_clock(world, monkeypatch):
    """`datetime.timestamp()` reads a naive value as LOCAL time. On a host five and
    a half hours ahead of UTC a revocation stamped one minute in the future would
    land five and a half hours in the past, and the token it should refuse would
    pass."""
    if not hasattr(time, "tzset"):
        pytest.skip("needs time.tzset")
    now = int(time.time())
    naive_utc = datetime.fromtimestamp(now + 60, timezone.utc).replace(tzinfo=None).isoformat()
    _with_revocation(world, naive_utc)
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    try:
        assert "revoked" in _refused(_staff, _token(iat=now)).lower()
    finally:
        monkeypatch.undo()
        time.tzset()


def test_a_revocation_with_a_token_that_cannot_say_when_it_was_issued_refuses(world, monkeypatch):
    """`iat` is a required claim on the real path; this is the belt to that
    braces — a decode that returned no `iat` (a double, or a future change to
    the required list) must not skip the comparison."""
    _with_revocation(world, "2020-01-01T00:00:00+00:00")
    monkeypatch.setattr(auth, "decode_supabase_jwt",
                        lambda _t: {"sub": "auth-user-1", "email": "p@f.in"})
    _refused(_staff, "anything")


def test_an_iat_of_zero_does_not_skip_the_revocation_check(world, monkeypatch):
    _with_revocation(world, "2020-01-01T00:00:00+00:00")
    monkeypatch.setattr(auth, "decode_supabase_jwt",
                        lambda _t: {"sub": "auth-user-1", "iat": 0})
    assert "revoked" in _refused(_staff, "anything").lower()


def test_no_revocation_is_the_ordinary_case(world):
    assert _staff(_token())["role"] == "Partner"


# ── the rule, not the two spellings ──────────────────────────────────────────

def test_there_is_one_place_a_token_is_decoded_and_none_skips_the_audience():
    """Two decodes each carrying their own options is how one of them stayed
    open. The count is the rule: a third `jwt.decode(` anywhere in apps/api is a
    third door that must earn its own checks."""
    found: list[str] = []
    for path in API_ROOT.rglob("*.py"):
        parts = set(path.parts)
        if parts & {"tests", ".venv", "venv", "__pycache__", "migrations", "node_modules"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        code = re.sub(r'"""(?:.|\n)*?"""', "", text)
        code = "\n".join(l.split("#", 1)[0] for l in code.splitlines())
        if re.search(r"\bjwt\.decode\(", code):
            found.append(path.relative_to(API_ROOT).as_posix())
        assert "verify_aud" not in code, (
            f"{path}: verify_aud appears in code — the audience is never switched off")
    assert found == ["core/auth.py"], found


def test_the_decode_passes_an_audience_an_issuer_and_the_required_claims():
    src = (API_ROOT / "core" / "auth.py").read_text(encoding="utf-8")
    body = src[src.index("def decode_supabase_jwt"):src.index("def _instant_epoch")]
    for needle in ("audience=", "issuer=", '"require"'):
        assert needle in body, f"decode_supabase_jwt lost {needle}"
    assert auth._JWT_REQUIRED_CLAIMS == ["exp", "sub", "iat"]
    assert auth._JWT_AUDIENCE == "authenticated"
