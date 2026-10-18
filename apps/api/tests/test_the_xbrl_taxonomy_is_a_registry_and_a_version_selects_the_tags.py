"""The MCA XBRL taxonomy is a registry with a verified marker, and a package's version selects its tags (POST-A-118).

WHAT WAS WRONG
    `taxonomy_version` was a string nothing read. A package could be created under any value, the validator and the XML
    writer used the same hand-typed tag table and the same namespace whatever it said, and no response or screen said that
    the tags had never been run through MCA's own validation tool.

WHAT IS HELD
    * `domain/income_tax/xbrl_taxonomy` is the one registry (`TAXONOMY_BY_VERSION`, `DEFAULT_TAXONOMY`,
      `LATEST_VERIFIED_TAXONOMY`). Today it holds `MCA_2023`, UNVERIFIED, and the marker is None; the two can only move together
      (a flag flipped without the marker, or the marker moved onto an unverified entry, fails here);
    * a version this product does not hold is refused (`UnknownTaxonomy`, a 422 at the API) and nothing is stored under it;
    * the validator and the XML writer take the tags and the namespace from the package's OWN version (driven with a second,
      synthetic entry: the namespace and prefix in the XML are that entry's, which the old hard-coded namespace could not give);
    * every response that names a version carries `taxonomy_notice`, the sentence saying it has not been checked, and the
      notice is never stored;
    * neither the service nor the router spells the default version or the namespace: they read the registry.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.permissions as permissions
import domain.income_tax.xbrl_service as svc
import domain.income_tax.xbrl_taxonomy as tax
import routers.xbrl_engine as xe
from core.auth import get_current_user

API_ROOT = Path(__file__).resolve().parents[1]
USER = {"id": "u1", "firm_id": "firm-1", "auth_user_id": "u1", "email": "e@f.test", "role": "Partner"}

SYNTHETIC = tax.Taxonomy(
    version="TEST_9",
    prefix="in-test",
    namespace="http://example.invalid/taxonomy/test9/in-test",
    mappings=(
        ("BalanceSheet.Equity.ShareCapital", "in-test:ShareCapital", "Share Capital", True),
        ("BalanceSheet.CurrentAssets.CashAndCashEquivalents", "in-test:Cash", "Cash", True),
    ),
)


@pytest.fixture(autouse=True)
def _clean_store():
    svc._MOCK_PACKAGES.clear()
    yield
    svc._MOCK_PACKAGES.clear()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(permissions, "can_user", lambda user, resource, action: True)
    monkeypatch.setattr(xe, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(xe, "can_access_client", lambda user, client_id: True)
    monkeypatch.setattr(xe.timeline_service, "log", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(xe.router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


# ── the registry itself ─────────────────────────────────────────────────────────────────────────────

def test_the_default_version_is_registered_and_unverified_and_nothing_is_marked_verified():
    assert tax.DEFAULT_TAXONOMY in tax.TAXONOMY_BY_VERSION
    assert tax.TAXONOMY_BY_VERSION[tax.DEFAULT_TAXONOMY].verified is False
    assert tax.LATEST_VERIFIED_TAXONOMY is None
    # Promoting a version is a human step (ledger POST-C-170: read MCA's page, download the validator and the taxonomies);
    # this test is what stops it being done without the marker.


def test_the_verified_flag_and_the_marker_only_move_together():
    verified = {v for v, t in tax.TAXONOMY_BY_VERSION.items() if t.verified}
    if tax.LATEST_VERIFIED_TAXONOMY is None:
        assert not verified, f"{sorted(verified)} are flagged verified but LATEST_VERIFIED_TAXONOMY is None"
    else:
        assert tax.LATEST_VERIFIED_TAXONOMY in tax.TAXONOMY_BY_VERSION
        assert tax.LATEST_VERIFIED_TAXONOMY in verified, "the marker names an entry that is not flagged verified"


@pytest.mark.parametrize("version", sorted(tax.TAXONOMY_BY_VERSION))
def test_every_entry_is_well_formed(version):
    entry = tax.TAXONOMY_BY_VERSION[version]
    assert entry.version == version
    assert entry.namespace.startswith("http://") and entry.prefix
    lines = [m[0] for m in entry.mappings]
    tags = [m[1] for m in entry.mappings]
    assert len(lines) == len(set(lines)) and len(tags) == len(set(tags)), "a schedule line or a tag is listed twice"
    assert all(len(m) == 4 and isinstance(m[3], bool) for m in entry.mappings)
    assert all(t.startswith(f"{entry.prefix}:") for t in tags), "a tag is not under the entry's own prefix"
    assert len(entry.mappings) >= 20


def test_a_blank_version_is_the_default_and_an_unregistered_one_is_refused_naming_what_is_held():
    assert tax.taxonomy_for(None).version == tax.DEFAULT_TAXONOMY
    assert tax.taxonomy_for("  ").version == tax.DEFAULT_TAXONOMY
    with pytest.raises(tax.UnknownTaxonomy) as refused:
        tax.taxonomy_for("MCA_2099")
    assert isinstance(refused.value, ValueError)
    assert "MCA_2099" in str(refused.value) and tax.DEFAULT_TAXONOMY in str(refused.value)


def test_the_notice_says_an_unverified_version_has_not_been_checked_and_a_verified_one_says_nothing(monkeypatch):
    assert "not been checked" in tax.taxonomy_notice("MCA_2023")
    monkeypatch.setitem(tax.TAXONOMY_BY_VERSION, "TEST_9", SYNTHETIC)
    monkeypatch.setitem(tax.TAXONOMY_BY_VERSION, "TEST_10", tax.Taxonomy(**{**SYNTHETIC.__dict__, "version": "TEST_10", "verified": True}))
    assert tax.taxonomy_notice("TEST_10") is None
    assert "not one this product holds" in tax.taxonomy_notice("NO_SUCH")


# ── the service: the version selects the tags and the namespace ──────────────────────────────────────

def _create(version=None):
    kwargs = {} if version is None else {"taxonomy_version": version}
    return svc.create_xbrl_package("firm-1", "c1", "2025-26", "u1", **kwargs)


def test_an_unregistered_version_is_refused_and_nothing_is_stored():
    with pytest.raises(tax.UnknownTaxonomy):
        _create("MCA_2099")
    assert svc._MOCK_PACKAGES == {}


def test_a_package_carries_the_notice_on_the_way_out_and_never_stores_it():
    package = _create()
    assert package["taxonomy_version"] == "MCA_2023" and "not been checked" in package["taxonomy_notice"]
    assert "taxonomy_notice" not in svc._MOCK_PACKAGES[package["id"]]
    listed = svc.list_xbrl_packages("firm-1", "c1")
    assert [p["taxonomy_notice"] for p in listed] == [package["taxonomy_notice"]]


def test_validation_and_the_xml_follow_the_packages_own_version(monkeypatch):
    monkeypatch.setitem(tax.TAXONOMY_BY_VERSION, "TEST_9", SYNTHETIC)
    package = _create("TEST_9")
    svc.update_xbrl_data("firm-1", package["id"],
                         balance_sheet_json={"BalanceSheet.Equity.ShareCapital": 10_000_00,
                                             "BalanceSheet.CurrentAssets.CashAndCashEquivalents": 10_000_00})
    checked = svc.validate_xbrl_package("firm-1", package["id"])
    # Under MCA_2023's table these two lines would leave a dozen mandatory tags missing; under TEST_9's they are all there is.
    assert checked["status"] == "validated" and checked["missing_tags"] == [], checked
    xml = svc.generate_xbrl_xml("firm-1", package["id"], "Client Ltd", "U00000MH2020PTC000000")
    assert 'xmlns:in-test="http://example.invalid/taxonomy/test9/in-test"' in xml
    assert "<in-test:ShareCapital" in xml and "in-bse-fin" not in xml


def test_the_default_version_still_writes_the_namespace_it_always_did():
    package = _create()
    svc._MOCK_PACKAGES[package["id"]].update(status="validated", balance_sheet_json={"BalanceSheet.Equity.ShareCapital": 100})
    xml = svc.generate_xbrl_xml("firm-1", package["id"], "Client Ltd", "U00000MH2020PTC000000")
    assert 'xmlns:in-bse-fin="http://www.mca.gov.in/taxonomy/2023/in-bse-fin"' in xml
    assert "<in-bse-fin:ShareCapital" in xml


def test_a_stored_version_this_product_does_not_hold_is_refused_not_checked_against_another():
    package = _create()
    svc._MOCK_PACKAGES[package["id"]]["taxonomy_version"] = "OLD_2019"
    with pytest.raises(tax.UnknownTaxonomy):
        svc.validate_xbrl_package("firm-1", package["id"])
    svc._MOCK_PACKAGES[package["id"]]["status"] = "validated"
    with pytest.raises(tax.UnknownTaxonomy):
        svc.generate_xbrl_xml("firm-1", package["id"], "Client Ltd", "U00000MH2020PTC000000")


def test_the_tag_table_is_the_versions_and_an_unknown_one_is_refused():
    assert len(svc.get_default_tag_mappings()) == len(tax.TAXONOMY_BY_VERSION["MCA_2023"].mappings) == 35
    assert svc.DEFAULT_MAPPINGS is tax.TAXONOMY_BY_VERSION["MCA_2023"].mappings
    with pytest.raises(tax.UnknownTaxonomy):
        svc.get_default_tag_mappings("MCA_2099")


# ── the API ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_api_refuses_an_unregistered_version_with_a_422_and_stores_nothing(client):
    refused = client.post("/api/xbrl/packages", json={"client_id": "c1", "financial_year": "2025-26", "taxonomy_version": "MCA_2099"})
    assert refused.status_code == 422, refused.text
    assert "MCA_2099" in refused.text and "MCA_2023" in refused.text
    assert svc._MOCK_PACKAGES == {}


def test_the_api_returns_the_notice_with_a_created_package_and_with_the_tag_table(client):
    created = client.post("/api/xbrl/packages", json={"client_id": "c1", "financial_year": "2025-26"})
    assert created.status_code == 200, created.text
    assert "not been checked" in created.json()["data"]["taxonomy_notice"]
    table = client.get("/api/xbrl/tag-mappings").json()["data"]
    assert table["taxonomy_version"] == "MCA_2023" and table["verified"] is False and "not been checked" in table["taxonomy_notice"]
    assert len(table["mappings"]) == 35
    assert client.get("/api/xbrl/tag-mappings", params={"taxonomy_version": "MCA_2099"}).status_code == 422


def test_the_api_returns_the_notice_with_the_generated_file(client):
    created = client.post("/api/xbrl/packages", json={"client_id": "c1", "financial_year": "2025-26"}).json()["data"]
    svc._MOCK_PACKAGES[created["id"]].update(status="validated", balance_sheet_json={"BalanceSheet.Equity.ShareCapital": 100})
    made = client.post(f"/api/xbrl/packages/{created['id']}/generate-xml", json={"client_name": "Client Ltd", "cin": "U00000MH2020PTC000000"})
    assert made.status_code == 200, made.text
    assert "not been checked" in made.json()["data"]["taxonomy_notice"]


def test_the_api_answers_a_stored_unregistered_version_with_a_422_on_validate_and_generate(client):
    created = client.post("/api/xbrl/packages", json={"client_id": "c1", "financial_year": "2025-26"}).json()["data"]
    svc._MOCK_PACKAGES[created["id"]].update(taxonomy_version="OLD_2019", status="validated")
    assert client.post(f"/api/xbrl/packages/{created['id']}/validate").status_code == 422
    assert client.post(f"/api/xbrl/packages/{created['id']}/generate-xml",
                       json={"client_name": "Client Ltd", "cin": "U00000MH2020PTC000000"}).status_code == 422


# ── the rule, not a spelling: nobody but the registry names a version or a namespace ───────────────

def _code(path: Path) -> str:
    """The source with comments and docstrings removed, so prose that explains the old behaviour does not count."""
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body[0].value.value = ""
    return ast.unparse(tree)


def test_neither_the_service_nor_the_router_spells_a_version_or_a_namespace():
    for relative in ("domain/income_tax/xbrl_service.py", "routers/xbrl_engine.py"):
        code = _code(API_ROOT / relative)
        assert "MCA_2023" not in code, f"{relative} names the version instead of reading DEFAULT_TAXONOMY"
        assert not re.search(r"mca\.gov\.in/taxonomy", code), f"{relative} spells the namespace instead of reading the registry"
        assert "in-bse-fin" not in code, f"{relative} spells the prefix instead of reading the registry"


def test_the_scan_sees_a_spelling_when_there_is_one(tmp_path):
    spelled = tmp_path / "spelled.py"
    spelled.write_text('"""doc"""\nVERSION = "MCA_2023"\nNS = "http://www.mca.gov.in/taxonomy/2023/in-bse-fin"\n', encoding="utf-8")
    code = _code(spelled)
    assert "MCA_2023" in code and "in-bse-fin" in code
