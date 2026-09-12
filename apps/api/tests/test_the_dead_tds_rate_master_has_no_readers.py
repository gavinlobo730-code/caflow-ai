"""
public.tds_section_limits is not the TDS rate master, and nothing may read it.

TDS-27. Migration 037 created a table whose name and columns read exactly like
the authoritative TDS rate table — section, description, threshold_paise,
rate_individual, rate_company, return_type — and seeded it once with figures
that were already going stale:

    194J  ₹30,000     (the limit is ₹50,000)
    194I  ₹2,40,000/yr (it is ₹50,000 a MONTH)
    194A  ₹4,000
    194D / 194G / 194H at 5%   (2%)

and its ₹1,00,000 aggregate §194C row has never existed in any database,
because `section` is the primary key and both 194C rows were inserted under
`ON CONFLICT (section) DO NOTHING`.

Nothing reads it. That is what makes it a trap rather than a bug: no CA sees a
wrong number today, and the first person to write a report or a dropdown
against it ships FY 2019-era thresholds with nothing failing. Migration 371
makes the table say so in the database; this holds the other half — that the
"nothing reads it" premise is still true.

The figures are deliberately NOT corrected in place. domain/tds/section_rates.py
is the FY-versioned authority with a LATEST_VERIFIED_TDS_FY a human moves
against the Finance Act, and a corrected copy of it in SQL is the second source
of truth CLAUDE.md's one-kernel rule exists to prevent.
"""
from __future__ import annotations

import re
from pathlib import Path

TABLE = "tds_section_limits"

_API = Path(".")
_WEB = Path("../web")

#: Where the name is allowed to appear: the migrations that create and grant it,
#: and this test.
_ALLOWED_SUFFIXES = (
    "migrations/037_tds_engine.sql",
    "migrations/041_grant_all_tables_to_authenticated.sql",
    "migrations/095_grant_reconciliation.sql",
    "migrations/371_the_dead_tds_rate_master_says_it_is_not_the_authority.sql",
    "migrations/371_the_dead_tds_rate_master_says_it_is_not_the_authority_rollback.sql",
    "tests/test_the_dead_tds_rate_master_has_no_readers.py",
)

#: The production snapshots record the table because it IS in production. They
#: are a picture of the database, not a reader of it — see docs/schema-drift.md.
_ALLOWED_PREFIXES = ("tests/fixtures/",)

_SEARCHED = ("*.py", "*.ts", "*.tsx", "*.sql", "*.json")


def _sql_string_after(sql: str, start: int) -> str:
    """The concatenated string literal of the statement beginning at `start`.

    SQL adjacent literals are one value, so a comment written over several
    lines is a single stored string; this joins them and unescapes `''`.
    """
    out, i, n = [], start, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            buf = []
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(sql[j])
                j += 1
            out.append("".join(buf))
            i = j + 1
            continue
        if ch == ";":
            break
        i += 1
    return "".join(out)


def _files():
    for root in (_API, _WEB):
        if not root.exists():
            continue
        for pattern in _SEARCHED:
            for path in root.rglob(pattern):
                text = str(path).replace("\\", "/")
                if any(part in text for part in
                       ("/node_modules/", "/.next/", "/__pycache__/", "/.git/")):
                    continue
                yield path, text


def test_no_code_reads_the_dead_rate_master():
    offenders = []
    for path, text in _files():
        if any(text.endswith(suffix) for suffix in _ALLOWED_SUFFIXES):
            continue
        if any(text.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
            continue
        try:
            body = path.read_text(errors="ignore")
        except OSError:
            continue
        if TABLE in body:
            offenders.append(text)
    assert offenders == [], (
        f"public.{TABLE} is seeded with pre-Finance-Act-2025 thresholds and "
        "pre-2024 rates and is not maintained. TDS rates, thresholds and the "
        "per-section aggregate limb are in apps/api/domain/tds/section_rates.py. "
        f"Reading it here ships stale statutory figures: {offenders}")


def test_the_table_says_in_the_database_that_it_is_not_the_authority():
    """A guard in the test suite is invisible to somebody reading the schema in
    a SQL client, which is where the temptation starts."""
    sql = Path("migrations/371_the_dead_tds_rate_master_says_it_is_not_the_"
               "authority.sql").read_text()
    start = sql.find("COMMENT ON TABLE public.tds_section_limits IS")
    assert start >= 0, "the table must carry a COMMENT"
    # Read to the statement's own terminator, which is the first ';' OUTSIDE a
    # quoted literal — the comment's prose contains semicolons of its own, and
    # a naive `.*?;` stopped at the first sentence.
    stored = _sql_string_after(sql, start)
    assert "NOT THE AUTHORITY" in stored
    assert "domain/tds/section_rates.py" in stored
    assert "Do not correct these figures in place" in stored


def test_the_authority_it_points_at_is_real_and_fy_versioned():
    """The comment names a module and a constant; both have to exist, or the
    pointer is worse than no pointer."""
    from domain.tds import section_rates
    assert hasattr(section_rates, "TDS_RATES_BY_FY")
    assert hasattr(section_rates, "LATEST_VERIFIED_TDS_FY")


def test_the_authority_disagrees_with_the_seeded_figures():
    """If these ever agreed, the guard above would be pointless — and the fact
    that they do not is the whole finding. §194J's threshold is the clearest:
    the table says ₹30,000, the Finance Act 2025 says ₹50,000."""
    from domain.tds import section_rates
    rates = section_rates.tds_rates_for(section_rates.LATEST_VERIFIED_TDS_FY)
    rule = rates.sections["194J"]
    assert rule.single_threshold_paise != 30000_00, (
        "the seeded table's ₹30,000 is a Finance Act behind; if the registry "
        "now says the same thing, check which one moved")
