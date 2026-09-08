"""A factory that takes a provider name must not ignore it.

WHY THIS EXISTS
    domain/gst/portal_service.get_provider took a `provider_name` and returned
    ManualGSTProvider unconditionally. The parameter read as a switch and was
    not one, so the day a GSP provider is added, a caller asking for it by name
    gets the MANUAL provider and no error — and in this module the manual
    provider's answers are empty lists and `{"status": "manual"}`. A CA reading
    that as "the portal says nothing is filed" is the whole failure, and it
    would be a silent one.

    That matters more here than in most factories because the data is read as
    FACT (what the portal holds) rather than posted as a document. The
    e-invoice factory already warned and fell back; this one refuses.

    docs/compliance/07-getting-permission-to-file.md is what actually gates a
    second provider existing: production GSTN credentials are a licence key
    issued only to an empanelled GSP, and there is no direct-to-GSTN route at
    any turnover.
"""
import pytest


def test_gst_portal_factory_returns_manual_for_manual():
    from domain.gst.portal_service import get_provider, ManualGSTProvider
    assert isinstance(get_provider("manual"), ManualGSTProvider)
    assert isinstance(get_provider(), ManualGSTProvider)


def test_gst_portal_factory_refuses_a_provider_it_does_not_have():
    from domain.gst.portal_service import get_provider
    with pytest.raises(ValueError) as ei:
        get_provider("gsp")
    msg = str(ei.value)
    # The message has to say what is missing and what to do, not just "invalid":
    # the reader is a developer wiring the second provider in.
    assert "gsp" in msg
    assert "manual" in msg
    assert "07-getting-permission-to-file" in msg


def test_a_bad_provider_name_never_leaves_a_sync_job_running(monkeypatch):
    """The refusal is resolved before the job is marked running.

    get_provider used to be called after the status update, so a name it could
    not serve would leave the row at "running" for ever with no error message.
    """
    import domain.gst.portal_service as ps

    updates: list[dict] = []

    class _Res:
        def __init__(self, data): self.data = data

    class _Q:
        def __init__(self, table): self.table_name = table; self._update = None
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def single(self): return self
        def update(self, payload): self._update = payload; updates.append(payload); return self
        def execute(self):
            if self._update is not None:
                return _Res([{}])
            return _Res({"id": "JOB", "gstin": "27ABCDE1234F1Z5", "client_id": "CLI",
                         "scope": ["profile"]})

    class _SB:
        def table(self, name): return _Q(name)

    monkeypatch.setattr(ps, "_USE_MOCK", False)
    monkeypatch.setattr(ps, "_supabase", lambda: _SB())

    with pytest.raises(ValueError):
        ps.run_sync_job("FIRM", "JOB", provider_name="gsp")

    assert updates == [], "the job must not be touched at all when the provider name is not one we have"
