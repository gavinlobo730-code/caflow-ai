"""The request id reaches the provider a request calls and the log lines of a scheduled run (POST-A-027).

WHAT WAS MISSING
    The id was bound to INBOUND requests only (ops-11): a CA could quote the reference a screen showed and find the request's own log
    lines, but not the call that request made to the mail provider, the payment gateway or a model, and a daily run's lines carried no
    reference at all, so "the invoice email did not go out last night" could not be followed from our log into the provider's.

WHAT IS HELD
    * `outbound_headers()` is `{X-Request-ID: <id>}` inside a request or a run and `{}` outside, and it carries the id and nothing
      else (no path, no firm, no person);
    * `job_run(name)` binds a `job-<name>-<8 hex>` id that obeys the same shape rule as a caller's, restores the previous context
      afterwards, and keeps a request's own id when the run is started inside one (a person's manual run);
    * the daily run is bound by it;
    * the provider call sites (the mail provider twice, the payment gateway twice, the model gateway) send the header, and a source
      rule names every outbound HTTP call in the server, so a new one is either given the header or listed with the reason it must not
      carry one.
"""
from __future__ import annotations

import ast
from pathlib import Path

from core import request_context as rc

API = Path(__file__).resolve().parent.parent


def test_outside_a_request_there_are_no_outbound_headers():
    assert rc.current_request_id() is None
    assert rc.outbound_headers() == {}


def test_inside_a_request_the_id_and_nothing_else_is_sent():
    token = rc.begin("0123456789abcdef")
    try:
        rc.current().firm_id = "firm-secret"
        assert rc.outbound_headers() == {"X-Request-ID": "0123456789abcdef"}
    finally:
        rc.end(token)
    assert rc.outbound_headers() == {}


def test_a_job_run_binds_an_id_of_the_accepted_shape_and_restores_what_was_there():
    with rc.job_run("daily") as rid:
        assert rid.startswith("job-daily-") and rc.clean_request_id(rid) == rid
        assert rc.outbound_headers() == {"X-Request-ID": rid}
    assert rc.current_request_id() is None


def test_a_job_name_that_is_not_safe_cannot_break_the_shape():
    with rc.job_run("a b/c\nd") as rid:
        assert rc.clean_request_id(rid) == rid and "\n" not in rid and "/" not in rid and " " not in rid


def test_a_run_started_inside_a_request_keeps_the_requests_own_id():
    token = rc.begin("aaaaaaaabbbbbbbb")
    try:
        with rc.job_run("daily") as rid:
            assert rid == "aaaaaaaabbbbbbbb" and rc.current_request_id() == "aaaaaaaabbbbbbbb"
        assert rc.current_request_id() == "aaaaaaaabbbbbbbb", "the run must not clear the request's context"
    finally:
        rc.end(token)


def test_the_daily_run_is_bound_by_a_job_context(monkeypatch):
    import jobs.scheduler as js
    seen = []
    monkeypatch.setattr(js, "_begin", lambda job, fid, force: seen.append(rc.current_request_id()) or False)
    monkeypatch.setattr(js, "_skip_reason", lambda job, fid: "test")
    js.run_daily_jobs("f1", True)
    assert seen and all(i.startswith("job-daily-") for i in seen) and len(set(seen)) == 1, "one run, one id, on every job"
    assert rc.current_request_id() is None
    assert js.run_daily_jobs.__name__ == "run_daily_jobs", "the decorator must keep the function's name (the lint baseline reads it)"


def test_the_mail_provider_receives_the_id(monkeypatch):
    import httpx
    import services.email_service as es
    sent = {}

    class _Resp:
        status_code = 200
        text = ""
        def json(self): return {"id": "m1"}

    monkeypatch.setattr(httpx, "post", lambda url, **kw: sent.update(kw) or _Resp())
    monkeypatch.setattr(es, "_RESEND_API_KEY", "re_test_key")
    token = rc.begin("feedfacefeedface")
    try:
        es.transport("a@example.test", "Subject", "<p>x</p>")
    finally:
        rc.end(token)
    assert sent["headers"]["X-Request-ID"] == "feedfacefeedface"


# ── the rule over the source ─────────────────────────────────────────────────────────

#: (file) -> why an outbound HTTP call there must NOT carry our id. Shrink-only.
REVIEWED = {
    "services/invoice_pdf_service.py":
        "fetches the logo image at a URL the practice typed; that host is not a provider of ours and has no business with our reference",
    "core/readiness.py":
        "the readiness probe asks our own dependencies whether they are up; there is no request to tie it to",
}
CALLS = {"post", "get", "put", "patch", "delete", "request", "stream"}


def _outbound_calls(path: Path):
    tree = ast.parse(path.read_text())
    uses_http = any(isinstance(n, (ast.Import, ast.ImportFrom)) and any(
        (getattr(a, "name", "") or "").split(".")[0] in ("httpx", "requests") or (getattr(n, "module", "") or "").split(".")[0] in ("httpx", "requests")
        for a in n.names) for n in ast.walk(tree))
    if not uses_http:
        return []
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in CALLS:
            base = n.func.value
            name = base.id if isinstance(base, ast.Name) else ""
            if name in ("httpx", "requests", "client"):
                out.append(n)
    return out


def test_every_outbound_http_call_sends_the_id_or_is_reviewed():
    problems = []
    for sub in ("services", "domain", "core", "routers", "jobs"):
        for path in (API / sub).rglob("*.py"):
            rel = str(path.relative_to(API))
            calls = _outbound_calls(path)
            if not calls or rel in REVIEWED:
                continue
            if "outbound_headers" not in path.read_text():
                problems.append(f"{rel}: {len(calls)} outbound HTTP call(s) and no outbound_headers()")
    assert not problems, "\n".join(problems)


def test_a_reviewed_file_still_makes_an_outbound_call():
    for rel in REVIEWED:
        assert _outbound_calls(API / rel), f"{rel} no longer makes an outbound call: delete its entry"
