"""
A branding image URL is a place the server will GO — no finding, found by the
12 September probe pass.

`services/invoice_pdf_service._remote_image` fetches any `http(s)` URL,
server-side, with `follow_redirects=True`, on every fee-invoice render.
`logo_url`, `secondary_logo_url` and `upi_qr_url` are free-form strings;
`PUT /api/settings/branding` validated the colours and the font family and
nothing else, and the settings screen offers a text box for the first.

So a Partner could point the API — which runs in Singapore, inside a provider
network — at `169.254.169.254`, at `localhost`, or at any internal address, and
have it issue the request when a PDF is built. Blind (every failure returns
None by design) and bounded (3 seconds, 2 MB), so a probe primitive rather than
an exfiltration path — but the control was missing and costs a few lines.

TWO CHECKS, NOT ONE, AND THEY ARE NOT REDUNDANT. The write boundary gives the
CA an error where the mistake was made; the fetch covers rows written before
the validation existed. `_accent_colour` already applies exactly this reasoning
to a colour: "re-validates on the way out rather than trusting a row written
before that validation".
"""
import pytest

from domain.branding.image_source import is_allowed, refusal


# ---------------------------------------------------------------------------
# The rule.
# ---------------------------------------------------------------------------
def test_an_ordinary_public_url_is_allowed():
    # The feature stays: a firm hosting its logo on its own site is supported,
    # and narrowing the allowlist to the storage bucket would break it.
    assert is_allowed("https://example.com/logo.png")


@pytest.mark.parametrize("url,fragment", [
    ("http://127.0.0.1/logo.png",          "loopback"),
    ("https://[::1]/logo.png",             "loopback"),
    ("http://169.254.169.254/latest/meta", "private"),   # every cloud's metadata
    ("http://10.0.0.5/logo.png",           "private"),
    ("http://172.16.0.9/logo.png",         "private"),
    ("http://192.168.1.1/logo.png",        "private"),
    ("http://0.0.0.0/logo.png",            "private"),
])
def test_an_internal_address_is_refused_and_says_why(url, fragment):
    problem = refusal(url)
    assert problem and fragment in problem


@pytest.mark.parametrize("url", [
    "https://localhost/logo.png",
    "https://metadata.google.internal/computeMetadata/v1/",
    "https://anything.internal/logo.png",
    "https://box.local/logo.png",
])
def test_an_internal_NAME_is_refused_whatever_it_resolves_to(url):
    assert refusal(url)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "gopher://x/", "ftp://x/a.png", "data:image/png;base64,AAAA",
    "/local/path.png", "", "   ", None,
])
def test_only_http_and_https_are_fetched(url):
    assert refusal(url)


def test_a_name_that_does_not_resolve_is_refused_rather_than_attempted():
    assert refusal("https://this-name-does-not-resolve.invalid/logo.png")


def test_the_refusal_is_a_sentence_and_never_an_exception():
    # It runs inside a document builder. A raise here is a PDF that does not
    # render, which is worse than a logo that does not appear.
    for junk in ("http://", "https://:99999", "http://[::", "http://a b c/"):
        assert isinstance(refusal(junk), (str, type(None)))


# ---------------------------------------------------------------------------
# The fetch follows redirects by hand, and re-asks at every hop.
# ---------------------------------------------------------------------------
def test_the_fetch_does_not_let_httpx_follow_redirects():
    # `follow_redirects=True` performs the next request before anything can
    # inspect where it went, which is the whole vector: a perfectly public URL
    # that 302s to 169.254.169.254. The hop loop is what replaces it.
    import inspect
    from services.invoice_pdf_service import _remote_image
    src = inspect.getsource(_remote_image)
    # Comments stripped: the note explaining why redirects are followed by hand
    # names the setting it replaced, and a guard its own explanation fails is a
    # guard nobody keeps.
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    assert "follow_redirects=False" in code
    assert "follow_redirects=True" not in code
    assert "image_source.refusal(nxt)" in src, "each hop must be re-asked"


def test_the_fetch_refuses_before_making_the_request(monkeypatch):
    import services.invoice_pdf_service as svc

    called = {"n": 0}

    class _Boom:
        def __init__(self, *a, **k):
            called["n"] += 1
            raise AssertionError("no request should have been made")

    monkeypatch.setattr("httpx.Client", _Boom)
    assert svc._remote_image("http://169.254.169.254/latest",
                             max_width_mm=10, max_height_mm=10) is None
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# The write boundary.
# ---------------------------------------------------------------------------
def test_saving_an_internal_logo_url_is_refused_with_a_422(monkeypatch):
    from fastapi import HTTPException
    import routers.branding as br

    monkeypatch.setattr(br.branding_repo, "get_branding", lambda f: {})
    monkeypatch.setattr(br.branding_repo, "upsert_branding",
                        lambda f, u: (_ for _ in ()).throw(
                            AssertionError("must not reach the repository")))

    with pytest.raises(HTTPException) as e:
        br.upsert_branding(br.BrandingUpdate(logo_url="http://169.254.169.254/x.png"),
                           {"firm_id": "F", "id": "u", "role": "Partner"})
    assert e.value.status_code == 422 and "logo_url" in e.value.detail


def test_both_branding_image_fields_are_checked(monkeypatch):
    from fastapi import HTTPException
    import routers.branding as br
    monkeypatch.setattr(br.branding_repo, "get_branding", lambda f: {})
    monkeypatch.setattr(br.branding_repo, "upsert_branding", lambda f, u: dict(u))
    for field in ("logo_url", "secondary_logo_url"):
        with pytest.raises(HTTPException) as e:
            br.upsert_branding(br.BrandingUpdate(**{field: "http://localhost/x.png"}),
                               {"firm_id": "F", "id": "u", "role": "Partner"})
        assert e.value.status_code == 422 and field in e.value.detail


def test_the_upi_qr_is_checked_on_ITS_OWN_writer(monkeypatch):
    # THE THIRD FIELD IS ON A DIFFERENT MODEL. `upi_qr_url` is on
    # InvoiceSettingsUpdate, not BrandingUpdate, and it is fetched by the same
    # `_remote_image`. A single loop over three names in one handler would have
    # guarded a field that never arrives there and left this one open.
    from fastapi import HTTPException
    import routers.branding as br
    monkeypatch.setattr(br.branding_repo, "get_invoice_settings", lambda f: {})
    monkeypatch.setattr(br.branding_repo, "upsert_invoice_settings",
                        lambda f, u: (_ for _ in ()).throw(
                            AssertionError("must not reach the repository")))
    with pytest.raises(HTTPException) as e:
        br.upsert_invoice_settings(
            br.InvoiceSettingsUpdate(upi_qr_url="http://169.254.169.254/qr.png"),
            {"firm_id": "F", "id": "u", "role": "Partner"})
    assert e.value.status_code == 422 and "upi_qr_url" in e.value.detail


def test_a_public_url_still_saves(monkeypatch):
    import routers.branding as br
    monkeypatch.setattr(br.branding_repo, "get_branding", lambda f: {})
    monkeypatch.setattr(br.branding_repo, "upsert_branding", lambda f, u: dict(u))
    monkeypatch.setattr(br, "_audit", lambda *a, **k: None)
    out = br.upsert_branding(br.BrandingUpdate(logo_url="https://example.com/logo.png"),
                             {"firm_id": "F", "id": "u", "role": "Partner"})
    assert out["success"] is True
    assert out["data"]["branding"]["logo_url"] == "https://example.com/logo.png"


def test_clearing_a_url_is_not_treated_as_an_internal_address(monkeypatch):
    # `update("logo_url", null)` is how the settings screen removes a logo.
    import routers.branding as br
    monkeypatch.setattr(br.branding_repo, "get_branding", lambda f: {})
    monkeypatch.setattr(br.branding_repo, "upsert_branding", lambda f, u: dict(u))
    monkeypatch.setattr(br, "_audit", lambda *a, **k: None)
    out = br.upsert_branding(br.BrandingUpdate(logo_url=None),
                             {"firm_id": "F", "id": "u", "role": "Partner"})
    assert out["success"] is True
