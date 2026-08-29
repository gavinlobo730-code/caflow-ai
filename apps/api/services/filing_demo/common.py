"""The shared vocabulary of the filing-demo walk-throughs.

WHAT THIS IS
    PracticeSync prepares every Indian statutory filing but cannot transmit
    any of them — real submission needs a GSP (GST), ERI registration (ITR),
    or has no public API at all (TDS upload, EPFO ECR, ESIC, MCA). The owner's
    direction (2026-08-29): every module still gets a FULL filing experience,
    portal-faithful in sequence and appearance, clearly a demo. This package
    is that experience's one implementation — a flow is data (a list of
    stages), the wizard renders it, and nothing anywhere transmits or writes.

THE THREE RULES EVERY FLOW OBEYS
    1. WRITES NOTHING. No status moves, no filings row, no period lock, no
       audit entry claiming a filing. tests/test_filing_demo_framework.py
       scans for writes the way the GSTR-3B tests do.
    2. THE SEQUENCE IS THE REAL PORTAL'S. A walk-through that invents its own
       order teaches a CA nothing they will recognise. Each flow module's
       docstring cites the real channel it mimics, and says whether software
       is permitted to transmit that filing in India today.
    3. REALISM IS LABELLED. A displayed reference may have the real
       authority's format — the owner's call, since a demo ending on an
       obviously fake string undercuts the walk-through — but it never
       travels without a SPECIMEN note, and the honest SIM-NOT-FILED
       reference is always in the same response.

Stages are plain dicts, one `kind` each; components/FilingDemoWizard.tsx is
the single renderer. Adding a stage kind means adding it in BOTH places —
which is why the vocabulary is small and the constructors below are the only
way flows build stages.
"""
from __future__ import annotations

import os
from typing import Optional


def filing_simulation_enabled() -> bool:
    """ON unless switched off — reversed from the original default, on the
    owner's explicit decision (2026-08-29).

    The first version shipped default-OFF, reasoning that a filing demo must
    never appear in production by accident. The owner then made demo filing a
    core product capability: every statutory module gets a portal-faithful
    walk-through, the deployment carries no real filings, and every screen of
    the flow is drenched in DEMO labelling — which is the real safeguard. The
    flag stays as the KILL SWITCH: set ENABLE_FILING_SIMULATION=false on any
    deployment that records real filings.
    """
    return os.environ.get("ENABLE_FILING_SIMULATION", "true").strip().lower() in (
        "1", "true", "yes", "on")


# ── Specimen references ──────────────────────────────────────────────────────
#
# Each mimics the real authority's format, deterministically from a seed (the
# record id), so a demo replays identically and needs no clock or randomness.
# Every one of these is display-only: the envelope carries the honest
# SIM-NOT-FILED reference alongside, and the result stage carries the
# specimen note. A specimen without its note is a bug the framework tests
# catch, not a style choice.

_CHECK = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def _digits(seed: str, n: int) -> str:
    """n deterministic digits from a seed: its own digits first, padded by a
    rolling character-sum so different seeds diverge even when digit-poor."""
    ds = "".join(c for c in str(seed) if c.isdigit())
    total = 0
    for c in str(seed):
        total = (total * 31 + ord(c)) % 10_000_000
    return (ds + str(total).zfill(7) * ((n // 7) + 2))[:n]


def _check_char(seed: str) -> str:
    return _CHECK[sum(ord(c) for c in str(seed)) % len(_CHECK)]


def specimen_gstn_arn(gstin: str, period: str, seed: str) -> str:
    """GSTN return ARN: 2 letters + state + MMYY + 6-digit serial + check."""
    state = gstin[:2] if len(gstin) >= 2 and gstin[:2].isdigit() else "27"
    mmyy = (period[:2] + period[4:6]) if len(period) == 6 else "0000"
    return f"AA{state}{mmyy}{_digits(seed, 6)}{_check_char(seed)}"


def specimen_tds_prn(seed: str) -> str:
    """e-TDS Provisional Receipt Number / token: 15 digits."""
    return _digits(seed, 15)


def specimen_itr_ack(seed: str) -> str:
    """e-filing acknowledgement number: 15 digits."""
    return _digits(seed, 15)


def specimen_epfo_trrn(seed: str) -> str:
    """EPFO ECR Temporary Return Reference Number: 10 digits."""
    return _digits(seed, 10)


def specimen_esic_challan(seed: str) -> str:
    """ESIC online challan number: 19 digits as issued by the portal."""
    return _digits(seed, 19)


def specimen_mca_srn(seed: str) -> str:
    """MCA Service Request Number: a letter then 8 digits."""
    return f"T{_digits(seed, 8)}"


SPECIMEN_NOTE = ("SPECIMEN — real {authority} format, but not issued by "
                 "{authority}. Nothing was filed.")


def honest_reference(flow: str, seed: str) -> str:
    """The reference that survives copying out of the demo. Deliberately not
    shaped like any authority's — it says on its face nothing was filed."""
    return f"SIM-NOT-FILED-{flow.upper()}-{str(seed)[:8]}"


# ── Stage constructors ───────────────────────────────────────────────────────
#
# The wizard's whole vocabulary. Every flow is a list of these; the wizard
# renders them in order, with three built-in behaviours: a declaration gates
# progress until ticked and a signatory chosen; a signature method with
# otp=True routes through the flow's otp stage while one with otp=False skips
# it; a transmit stage plays its steps and advances itself.

def summary_stage(title: str, note: str, figures: list, cta: str = "Proceed") -> dict:
    """figures: [{"label": str, "paise": int} | {"label": str, "text": str}]"""
    return {"kind": "summary", "title": title, "note": note,
            "figures": figures, "cta": cta}


def table_stage(title: str, note: str, columns: list, rows: list,
                footer: Optional[list] = None, cta: str = "Proceed") -> dict:
    """rows/footer cells: {"text": str} | {"paise": int}."""
    return {"kind": "table", "title": title, "note": note, "columns": columns,
            "rows": rows, "footer": footer, "cta": cta}


def declaration_stage(text: str, signatory_label: str, signatory_options: list,
                      note: str) -> dict:
    """`text` must be the form's own wording, verbatim — paraphrasing a
    statutory declaration misrepresents what the signatory affirms. `note`
    says WHOSE signature this is; for every Indian filing that is the
    taxpayer's (or a director's), never the firm's, and that fact is the
    single most important thing these demos teach."""
    return {"kind": "declaration", "text": text,
            "signatory_label": signatory_label,
            "signatory_options": signatory_options, "note": note}


def signature_stage(methods: list) -> dict:
    """methods: [{"key","label","note","otp": bool}]. otp=True routes through
    the otp stage (EVC, Aadhaar OTP); otp=False skips it (DSC/emSigner)."""
    return {"kind": "signature", "methods": methods}


def otp_stage(prompt: str, note: str) -> dict:
    """Any six digits pass. There is no OTP to be right about — inventing a
    'correct' one would teach a number that means nothing, and rejecting a
    wrong one would imply something checked it."""
    return {"kind": "otp", "prompt": prompt, "note": note}


def warning_stage(text: str, cta: str = "Proceed") -> dict:
    """The portal's irreversibility/freeze warning, naming the lawful
    correction route rather than reading as a dead end."""
    return {"kind": "warning", "text": text, "cta": cta}


def transmit_stage(steps: list) -> dict:
    """steps: [{"key","label"}] — the last stage of a real filing, played as
    a paced checklist. Paced for legibility, not to imitate a round trip:
    nothing is being transmitted."""
    return {"kind": "transmit", "steps": steps}


def result_stage(authority: str, reference_label: str, specimen: str,
                 filed_line: str, truth: list) -> dict:
    """The success panel. `specimen` is realistic in shape and ALWAYS rendered
    with the SPECIMEN badge and note (the wizard does this unconditionally);
    `truth` lines state what really happened and how to file for real."""
    return {"kind": "result", "authority": authority,
            "reference_label": reference_label, "specimen": specimen,
            "specimen_note": SPECIMEN_NOTE.format(authority=authority),
            "filed_line": filed_line, "truth": truth}


# ── The envelope every flow returns ──────────────────────────────────────────

def envelope(flow: str, title: str, subtitle: str, seed: str,
             real_channel: dict, stages: list) -> dict:
    """real_channel: {"how": str, "software_permitted": bool, "note": str} —
    the genuine submission mechanics this demo mimics, and whether Indian law
    and infrastructure let third-party software transmit it today. Stated in
    the payload so every module's demo teaches the same truthfully."""
    return {
        "simulated": True,
        "filed": False,
        "flow": flow,
        "title": title,
        "subtitle": subtitle,
        "acknowledgement": honest_reference(flow, seed),
        "real_channel": real_channel,
        "stages": stages,
        "disclaimer": (
            "SIMULATION — nothing was transmitted to any government system and "
            "nothing has been filed. PracticeSync prepares this filing; "
            "submission happens on the authority's own portal. No stored "
            "status has changed."
        ),
    }
