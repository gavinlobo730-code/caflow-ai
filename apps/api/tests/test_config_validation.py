"""
The boot-time configuration report.

WHY THIS FILE EXISTS
    core/config_validation.py had no tests at all, and its value is entirely in
    what it LISTS — a variable missing from _CONFIG is a variable whose absence
    is invisible at boot.

    That is not hypothetical. RESEND_API_KEY was absent from the list for the
    whole life of the email feature. email_service returns False and logs when
    it is unset, which is the right behaviour — a failed send must not break the
    action that triggered it — but combined with an unlisted variable it meant a
    deployment could send zero emails, for weeks, with nothing anywhere saying
    so. Every portal invite, team invite and scheduled report goes through that
    one key.

WHAT IT DOES NOT DO
    It does not assert an exact list. Pinning the whole set would turn every
    legitimate addition into a failing test with no information in it. It checks
    the properties that actually matter: the two variables without which the app
    cannot work are marked required, the ones with working defaults are not, and
    every entry is well-formed and carries a note.
"""
import core.config_validation as cv


def _by_name() -> dict[str, tuple[bool, str]]:
    return {name: (required, note) for name, required, note in cv._CONFIG}


def test_only_supabase_is_required():
    """Required means "the app cannot operate" — it is logged at ERROR. Marking
    anything else required would cry wolf on a deployment that is fine."""
    required = {n for n, (req, _) in _by_name().items() if req}
    assert required == {"SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"}, required


def test_every_feature_key_is_listed():
    """The point of the file. Each of these disables a whole feature silently
    when unset, so each has to appear in the boot report."""
    names = set(_by_name())
    for key in ("GROQ_API_KEY", "GEMINI_API_KEY", "SENTRY_DSN", "RESEND_API_KEY"):
        assert key in names, f"{key} is unlisted — its absence would be invisible at boot"


def test_resend_is_optional_not_required():
    """Optional on purpose: the app runs fine without email, it just cannot
    send. Making it required would put a red ERROR line in every local and
    preview boot."""
    required, note = _by_name()["RESEND_API_KEY"]
    assert required is False
    assert note, "say what stops working without it"


def test_email_from_is_deliberately_absent():
    """Not an oversight. email_service defaults it to a real address, so a
    missing EMAIL_FROM degrades the From header rather than stopping delivery —
    listing it would report a problem that is not one."""
    assert "EMAIL_FROM" not in _by_name()

    import services.email_service as es
    assert es._FROM_EMAIL, "EMAIL_FROM lost its default — then it DOES belong in _CONFIG"


def test_every_entry_is_well_formed():
    for entry in cv._CONFIG:
        assert len(entry) == 3, entry
        name, required, note = entry
        assert name.isupper() and name.replace("_", "").isalnum(), name
        assert isinstance(required, bool), name
        assert len(note) > 10, f"{name}: the note is what an operator reads"


def test_validate_config_reports_what_is_missing(monkeypatch):
    """The function's actual contract, exercised rather than assumed."""
    for name, _r, _n in cv._CONFIG:
        monkeypatch.delenv(name, raising=False)
    result = cv.validate_config()
    assert set(result["missing_required"]) == {"SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"}
    assert "RESEND_API_KEY" in result["missing_optional"]


def test_a_set_variable_is_not_reported_missing(monkeypatch):
    """Vacuity guard: without this, a validate_config() that reported EVERY
    variable as missing would pass the test above."""
    for name, _r, _n in cv._CONFIG:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    result = cv.validate_config()
    assert "RESEND_API_KEY" not in result["missing_optional"]
