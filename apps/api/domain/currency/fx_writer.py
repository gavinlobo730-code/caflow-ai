"""The client the two foreign-exchange record tables are WRITTEN with.

`fx_adjustments` (the realised and unrealised FX gain or loss behind a settlement or a revaluation, which the FX reports and the
vendor statement read back) and `fx_revaluations` (the rows the next revaluation diffs against, so a forged one changes the next
journal) are written by the API only. A signed-in session will not be allowed to write either (a migration that follows this
change takes the grant away), so their writers use the privileged client where there is one, the caller's own where there is no
other (mock mode, a test double), and `None` stays `None`.

Every route that reaches a write here has already checked the caller's access to the client, and every statement names the firm
and the client, because the privileged client carries no row security. Reads stay on the caller's client: row security is the
second lock there.
"""
from __future__ import annotations


def fx_writer(request_db):
    if not request_db:
        return request_db
    from core import db_provider
    return db_provider.service_db_or_none() or request_db
