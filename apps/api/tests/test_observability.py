"""
core/observability.py — Sentry capture for fail-soft posting failures (task #244).
"""
import logging

import sentry_sdk

from core.observability import capture_posting_failure


def test_captures_exception_with_operation_fingerprint_and_context(monkeypatch):
    captured = {}

    def fake_capture_exception(exc):
        captured["exc"] = exc
        return "event-id"

    monkeypatch.setattr(sentry_sdk, "capture_exception", fake_capture_exception)

    scopes = []
    real_new_scope = sentry_sdk.new_scope

    class _RecordingScope:
        def __init__(self):
            self.tags = {}
            self.extras = {}
            self.fingerprint = None

        def set_tag(self, k, v):
            self.tags[k] = v

        def set_extra(self, k, v):
            self.extras[k] = v

    class _CM:
        def __enter__(self):
            s = _RecordingScope()
            scopes.append(s)
            return s

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(sentry_sdk, "new_scope", lambda: _CM())

    err = ValueError("boom")
    capture_posting_failure(
        err, operation="post_cogs_journal_entry",
        firm_id="F1", client_id="C1", source_id="INV-1", note=None,
    )

    assert captured["exc"] is err
    scope = scopes[0]
    assert scope.tags["posting_operation"] == "post_cogs_journal_entry"
    assert scope.fingerprint == ["posting-failure", "post_cogs_journal_entry"]
    assert scope.tags["firm_id"] == "F1"
    assert scope.extras["client_id"] == "C1"
    assert "note" not in scope.tags  # None-valued context is skipped, not stringified to "None"


def test_logs_at_error_level_so_it_reaches_sentrys_default_logging_integration(monkeypatch, caplog):
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda exc: None)
    with caplog.at_level(logging.ERROR, logger="caflow.observability"):
        capture_posting_failure(ValueError("boom"), operation="post_inventory_receipt_journal_entry")
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_never_raises_even_if_sentry_itself_errors(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("sentry is down")

    monkeypatch.setattr(sentry_sdk, "new_scope", _boom)
    # Must not propagate — a fail-soft path's error-reporting call can never
    # itself become the second failure.
    capture_posting_failure(ValueError("boom"), operation="post_cogs_journal_entry")
