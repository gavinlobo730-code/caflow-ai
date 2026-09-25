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

    def put(self, path, body=None):
        return self._check("PUT", path, self.client.put(path, json=body or {}))


@pytest.fixture
def api():
    from fastapi.testclient import TestClient
    from main import app
    return _TestClientApi(TestClient(app))


def a_firm_mock_mode_can_carry():
    """The practice, with the PAYROLL leg removed — and the reason matters.

    ⚠️ MOCK MODE STRUCTURALLY CANNOT WALK A PAYROLL YEAR.
    `routers/payroll.create_employee` answers `{"id": "mock-id"}` with no
    database, and `create_run` answers `{"id": "mock-run"}` — CONSTANTS, not a
    store. So the second employee collides with the first (the attendance door
    refuses a roster with one id sent twice, correctly), and twelve runs are
    one run finalized twelve times. Stripping payroll here is not a smaller
    claim about the seeder; it is the largest one this harness can make.

    ⚠️ AND THE MSMED CLASSIFICATION IS THE SECOND ONE, for the opposite
    reason. `POST /accounting/schedule-iii/ageing/classify` answers 503 — *no
    database configured — a classification cannot be recorded* — rather than
    pretending, which is the right refusal and means this harness cannot reach
    it either. Its body is checked in the module named below, where nothing
    executes a router.

    The payroll leg is covered instead by
    `test_every_body_the_seeder_sends_is_one_its_door_accepts.py`, which runs
    the same `seed()` against the app's own route table and validates every
    body — the class of defect that was actually live there (two fields sent
    under names `EmployeeIn` does not declare, and silently dropped).
    """
    import dataclasses
    from domain.demo import fixture

    firm = fixture.build()
    return dataclasses.replace(firm, clients=tuple(
        dataclasses.replace(
            c, employees=(), payroll=(),
            vendors=tuple(dataclasses.replace(v, msme_status=None,
                                              msmed_agreement_days=None)
                          for v in c.vendors))
        for c in firm.clients))


def test_the_whole_practice_writes_through_the_doors(api):
    """The run the 32 fixture tests could not do. Every document goes through
    the router that would refuse it."""
    from domain.demo import fixture
    from scripts.seed_demo_firm import seed

    firm = a_firm_mock_mode_can_carry()
    written = seed(api, firm, add_to_existing=True)

    s = fixture.summary(firm)
    assert written["clients"] == s["clients"]
    assert written["sales_invoices"] == s["sales_invoices"]
    assert written["purchase_bills"] == s["purchase_bills"]
    # The two steps the first run did not know about.
    assert written["hsn_library"] > 0, "no HSN library was written"
    assert written["catalogue"] == sum(len(c.catalogue) for c in firm.clients)
    # And the three modules this tranche added, each of which was empty in the
    # demo until now.
    assert written["bank_accounts"] == s["bank_accounts"] > 0
    assert written["fixed_assets"] == s["fixed_assets"] > 0
    assert written["bank_lines"] > 0, "no statement line reached the queue"


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
    seed(api, a_firm_mock_mode_can_carry(), add_to_existing=True)

    first_doc = next(i for i, p in enumerate(seen) if "sales-invoices" in p)
    first_cat = next(i for i, p in enumerate(seen) if "service-catalogue" in p)
    first_lib = next(i for i, p in enumerate(seen) if "firm-hsn-library" in p)
    assert first_lib < first_cat < first_doc, (
        "library → catalogue → document is a precondition chain, not a "
        f"preference. Got library@{first_lib} catalogue@{first_cat} "
        f"document@{first_doc}"
    )


def test_the_bank_account_exists_before_the_receipt_that_names_it(api):
    """ORDER again, and for the same reason the catalogue chain is asserted as
    an order. Every receipt, vendor payment and asset purchase carries
    `bank_account_id`, so the money lands in the client's own ledger instead
    of `resolve_payment_account`'s generic `%Bank%` fallback — and a seeder
    that created the account afterwards would write a whole year of postings
    each carrying the fallback disclosure, which is a real notice the CA is
    meant to read."""
    from scripts.seed_demo_firm import seed

    seen: list[str] = []
    original = api.post

    def recording(path, body=None):
        seen.append(path)
        return original(path, body)

    api.post = recording
    seed(api, a_firm_mock_mode_can_carry(), add_to_existing=True)

    first_bank = next(i for i, p in enumerate(seen) if p == "/api/banking/accounts")
    first_receipt = next(i for i, p in enumerate(seen) if p == "/api/receipts/")
    first_asset = next(i for i, p in enumerate(seen) if p == "/api/fixed-assets")
    assert first_bank < first_receipt, f"bank@{first_bank} receipt@{first_receipt}"
    assert first_bank < first_asset, f"bank@{first_bank} asset@{first_asset}"


def test_the_statement_is_imported_after_every_invoice_is_known(api):
    """The credits on it are open invoices' own totals, read off the create
    responses — so the import cannot precede the last invoice of that client.
    Asserted per client rather than globally: a check on the FIRST import
    against the LAST invoice anywhere passes on a seeder that imports client
    one's statement before client one's invoices are written."""
    from scripts.seed_demo_firm import seed

    seen: list[str] = []
    original = api.post

    def recording(path, body=None):
        seen.append(path)
        return original(path, body)

    api.post = recording
    seed(api, a_firm_mock_mode_can_carry(), add_to_existing=True)

    # Walk in order: between two imports there must be no invoice that belongs
    # to the client whose statement was just imported. The seeder writes one
    # client at a time, so "an import is never followed by an invoice before
    # the next client's bank account" is the same statement and needs no ids.
    for i, path in enumerate(seen):
        if path != "/api/banking/statements/import":
            continue
        rest = seen[i + 1:]
        nxt = next((j for j, p in enumerate(rest) if p == "/api/banking/accounts"),
                   len(rest))
        assert "/api/sales-invoices/" not in rest[:nxt], (
            "a statement was imported before that client's last invoice, so "
            "its open-invoice credits cannot be the engine's own totals")


def test_a_firm_with_clients_is_refused_without_the_flag(api):
    """The one refusal that protects a real book. Asserted because it is the
    difference between a demo and an unrecoverable merge: a posted journal
    cannot be hard-deleted (migration 251)."""
    from domain.demo import fixture
    from scripts.seed_demo_firm import seed

    seed(api, a_firm_mock_mode_can_carry(), add_to_existing=True)
    with pytest.raises(SystemExit) as caught:
        seed(api, a_firm_mock_mode_can_carry(), add_to_existing=False)
    assert "already has" in str(caught.value)


def test_the_money_is_written_and_the_book_is_not_all_one_thing(api):
    """A book where nothing is paid teaches a CA nothing, and one where
    everything is teaches them less. The assertion is on the SPREAD, because
    either extreme passes a count."""
    from domain.demo import fixture
    from scripts.seed_demo_firm import seed

    firm = a_firm_mock_mode_can_carry()
    written = seed(api, firm, add_to_existing=True)
    s = fixture.summary(firm)

    assert written["receipts"] == s["receipts"] > 0
    assert written["payments"] == s["vendor_payments"] > 0
    # Both ends of the ageing have to exist or the screens a CA judges this on
    # say one thing: all current, or all collected.
    assert s["invoices_still_open"] > 0, "every invoice is settled — no ageing"
    assert s["receipts"] > s["invoices_still_open"], (
        "more invoices outstanding than collected reads as an insolvent client, "
        "not as a practice worth demonstrating"
    )
    # The case the matcher's own band and the settlement modal exist for.
    assert s["part_settled_invoices"] > 0, (
        "nothing is PART paid, so `outstanding_paise` equals the face value on "
        "every row and FindMatchModal's '· ₹X open' never renders"
    )
    assert s["receipts_with_tds_withheld"] > 0, (
        "no receipt carries withheld TDS, so TDS Receivable is structurally "
        "nil and SALES-07's settlement = amount + tds is never exercised"
    )


def test_the_settlement_never_exceeds_what_the_document_is_for(api):
    """`fraction_bps` is basis points of the document's own total, so a
    fraction over par would over-allocate — which the server refuses, and
    which would stop the run. Asserted on the DATA as well, because a fixture
    that can only be caught by a 422 is a fixture nobody can reason about."""
    from domain.demo import fixture

    for c in fixture.build().clients:
        for d in (*c.sales, *c.purchases):
            st = d.settlement
            if st is None:
                continue
            assert 0 < st.fraction_bps <= 10_000, f"{c.name} {d.doc_date}"
            assert 0 <= st.tds_bps < 10_000, f"{c.name} {d.doc_date}"
            if st.paid_after_days is not None:
                assert st.paid_after_days > 0


def test_adding_the_money_did_not_reshuffle_the_documents(api):
    """The settlement draws come from their OWN random stream, so that adding
    payments could not change which documents exist. It did on the first
    attempt — purchase bills went 200 to 236 — and every count in the tests
    and the plan silently became wrong for a change meant to be additive."""
    from domain.demo import fixture

    s = fixture.summary(fixture.build())
    assert s["sales_invoices"] == 315
    assert s["purchase_bills"] == 200
    assert s["customers"] == 31 and s["vendors"] == 30


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
