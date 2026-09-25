"""The demo seeder is RUN here, against the real routers, not read.

── WHY THIS MODULE EXISTS ───────────────────────────────────────────────────
`scripts/seed_demo_firm.py` and `domain/demo/fixture.py` shipped with 32 tests
between them and the script **had never once been executed**. Every one of
those tests read the FIXTURE — the counts, the GSTIN check digits, the dates —
which is the half that was right. The first real run died on the first client's
first invoice:

    POST /api/sales-invoices/ → HTTP 422
    "Product/Service is required on every line item … a new client has an
     empty catalogue until somebody adds to it."

`client_sales_invoice_lines` has required a `service_catalogue_id` since
migration 206, and `routers/service_catalogue._hsn_in_library` in turn refuses
a catalogue item whose HSN is not in the firm's own library (Decision C). So
the real order is **library → catalogue → document**, three steps where the
seeder had one, and no amount of reading the fixture could have said so.

CLAUDE.md already records the general form of this, from `fetch_all`'s two
broken call sites: *"a service whose job is to FETCH needs a test that
FETCHES"*. A seeder whose job is to WRITE needs a test that WRITES.

── HOW IT RUNS WITHOUT A SERVER ─────────────────────────────────────────────
`seed()` takes anything with `.get(path)` and `.post(path, body)`, so the
adapter below speaks that to a `TestClient` instead of to a socket. The
ROUTERS are real — rbac, the validators, the invoice-series rule, the GSTIN
check digit and the catalogue gate all run — which is the whole property the
seeder's own header claims for itself.

⚠️ WHAT THIS DOES NOT PROVE. Mock mode is FakeDB, not Postgres, so this says
nothing about the posting kernel's double-entry assertion or about anything
enforced by a CHECK. It proves the ORDER, the payload shapes and the
preconditions — which is exactly the class the 32 fixture tests could not see.
"""
import pytest

pytestmark = pytest.mark.usefixtures("dev_header_auth")


class _TestClientApi:
    """The seeder's `Api` surface, spoken to a TestClient. Mirrors its
    behaviour where it matters: it RAISES on a non-2xx rather than returning
    the body, because a seeder that walks past a 422 writes a hundred rows
    pointing at nothing — the same reason the real client has no retries."""

    def __init__(self, client):
        self.client = client
        self.calls = 0

    def _check(self, method: str, path: str, resp):
        self.calls += 1
        assert resp.status_code < 300, (
            f"{method} {path} → HTTP {resp.status_code}\n{resp.text[:400]}"
        )
        body = resp.json()
        assert body.get("success") is not False, (
            f"{method} {path} answered success=false: {str(body)[:300]}"
        )
        return body

    def get(self, path):
        return self._check("GET", path, self.client.get(path))

    def post(self, path, body=None):
        return self._check("POST", path, self.client.post(path, json=body or {}))


@pytest.fixture
def api():
    from fastapi.testclient import TestClient
    from main import app
    return _TestClientApi(TestClient(app))


def test_the_whole_practice_writes_through_the_doors(api):
    """The run the 32 fixture tests could not do. Every document goes through
    the router that would refuse it."""
    from domain.demo import fixture
    from scripts.seed_demo_firm import seed

    firm = fixture.build()
    written = seed(api, firm, add_to_existing=True)

    s = fixture.summary(firm)
    assert written["clients"] == s["clients"]
    assert written["sales_invoices"] == s["sales_invoices"]
    assert written["purchase_bills"] == s["purchase_bills"]
    assert written["employees"] == s["employees"]
    # The two steps the first run did not know about.
    assert written["hsn_library"] > 0, "no HSN library was written"
    assert written["catalogue"] == sum(len(c.catalogue) for c in firm.clients)


def test_the_catalogue_is_written_before_any_document_needs_it(api):
    """The ORDER is the finding, so it is asserted as an order rather than as
    a pair of counts — counts pass on a seeder that writes the catalogue
    afterwards, which is the bug this module exists for."""
    from domain.demo import fixture
    from scripts.seed_demo_firm import seed

    seen: list[str] = []
    original = api.post

    def recording(path, body=None):
        seen.append(path)
        return original(path, body)

    api.post = recording
    seed(api, fixture.build(), add_to_existing=True)

    first_doc = next(i for i, p in enumerate(seen) if "sales-invoices" in p)
    first_cat = next(i for i, p in enumerate(seen) if "service-catalogue" in p)
    first_lib = next(i for i, p in enumerate(seen) if "firm-hsn-library" in p)
    assert first_lib < first_cat < first_doc, (
        "library → catalogue → document is a precondition chain, not a "
        f"preference. Got library@{first_lib} catalogue@{first_cat} "
        f"document@{first_doc}"
    )


def test_a_firm_with_clients_is_refused_without_the_flag(api):
    """The one refusal that protects a real book. Asserted because it is the
    difference between a demo and an unrecoverable merge: a posted journal
    cannot be hard-deleted (migration 251)."""
    from domain.demo import fixture
    from scripts.seed_demo_firm import seed

    seed(api, fixture.build(), add_to_existing=True)   # now the firm has clients
    with pytest.raises(SystemExit) as caught:
        seed(api, fixture.build(), add_to_existing=False)
    assert "already has" in str(caught.value)


def test_every_catalogue_item_says_goods_or_services(api):
    """`kind` is DERIVED from the code (Chapter 99 is a SAC), so this is really
    a check that the fixture's two lists have not been mixed up — which would
    put a UQC on a service and take one off a good."""
    from domain.demo import fixture

    for c in fixture.build().clients:
        for item in c.catalogue:
            expected = "service" if item.hsn_sac_code.startswith("99") else "good"
            assert item.kind == expected, f"{item.name} {item.hsn_sac_code}"
            assert item.hsn_type == ("services" if expected == "service" else "goods")
