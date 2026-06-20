"""
Shared Indian tax identifier validators.
GSTIN: CGST Act §25 — 15-char format: 2-digit state + 10-char PAN + 1 entity + Z + 1 check
PAN:   IT Act §139A — AAAAA9999A (5 upper + 4 digit + 1 upper)
CIN:   Companies Act 2013 — 21-char: L/U + 5 digit + 2 upper state + 3 digit category + 4 digit year + 6 seq
TAN:   IT Act §203A — AAAA99999A (4 upper + 5 digit + 1 upper)
"""
import re
from typing import Optional

# ── Regex patterns ─────────────────────────────────────────────────────────────

_GSTIN_RE = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)
_PAN_RE   = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
_TAN_RE   = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]{1}$")
_CIN_RE   = re.compile(
    r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$"
)
_PHONE_RE  = re.compile(r"^\+?[\d\s\-]{10,16}$")  # allows spaces/hyphens; e.g. +91 98765 43210
_EMAIL_RE  = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")

# Two-digit state codes per GST council
_VALID_STATE_CODES = {
    "01","02","03","04","05","06","07","08","09","10",
    "11","12","13","14","15","16","17","18","19","20",
    "21","22","23","24","25","26","27","28","29","30",
    "31","32","33","34","35","36","37","38","97","99",
}


def validate_gstin(value: Optional[str]) -> Optional[str]:
    """Return None if valid, error message string if invalid.
    CGST Act §25: GSTIN format: 2-digit state + PAN(10) + entity + Z + check.
    Returns an error when value is None/empty — GSTIN is required.
    """
    if not value:
        return "GSTIN is required. CGST Act §25: every registered person must have a valid GSTIN."
    v = value.strip().upper()
    if not _GSTIN_RE.match(v):
        return "GSTIN format is invalid. Expected: 2-digit state + PAN + 1 entity + Z + 1 check (e.g. 27AAAAA0000A1Z5)."
    if v[:2] not in _VALID_STATE_CODES:
        return f"GSTIN state code '{v[:2]}' is not a valid Indian state code."
    return None


def validate_pan(value: Optional[str]) -> Optional[str]:
    """Return None if valid, error message string if invalid."""
    if not value:
        return None  # PAN is often optional (unregistered entities)
    v = value.strip().upper()
    if not _PAN_RE.match(v):
        return "PAN format is invalid. Expected: AAAAA9999A (5 uppercase letters + 4 digits + 1 uppercase letter)."
    return None


def validate_tan(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().upper()
    if not _TAN_RE.match(v):
        return "TAN format is invalid. Expected: AAAA99999A."
    return None


def validate_cin(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().upper()
    if not _CIN_RE.match(v):
        return "CIN format is invalid. Expected: L/U + 5 digits + 2-char state + 4-digit year + 3-char category + 6-digit seq (e.g. L17110MH1973PLC019786)."
    return None


def validate_phone(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if not _PHONE_RE.match(v):
        return "Phone number must be 10–13 digits (optionally prefixed with +)."
    return None


def validate_email(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if not _EMAIL_RE.match(value.strip()):
        return "Email address format is invalid."
    return None


def validate_pincode(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if not _PINCODE_RE.match(str(value).strip()):
        return "PIN code must be a 6-digit number starting with a non-zero digit."
    return None


def validate_state_code(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if str(value).strip() not in _VALID_STATE_CODES:
        return f"State code '{value}' is not a valid 2-digit Indian state code."
    return None


# Canonical GST state name → 2-digit code map (GST council list). Reference data.
INDIAN_STATE_CODES: dict[str, str] = {
    "jammu and kashmir": "01", "jammu & kashmir": "01",
    "himachal pradesh": "02", "punjab": "03", "chandigarh": "04",
    "uttarakhand": "05", "haryana": "06", "delhi": "07",
    "rajasthan": "08", "uttar pradesh": "09", "bihar": "10",
    "sikkim": "11", "arunachal pradesh": "12", "nagaland": "13",
    "manipur": "14", "mizoram": "15", "tripura": "16",
    "meghalaya": "17", "assam": "18", "west bengal": "19",
    "jharkhand": "20", "odisha": "21", "orissa": "21",
    "chhattisgarh": "22", "madhya pradesh": "23", "gujarat": "24",
    "daman and diu": "25", "dadra and nagar haveli": "26",
    "maharashtra": "27", "karnataka": "29", "goa": "30",
    "lakshadweep": "31", "kerala": "32", "tamil nadu": "33",
    "puducherry": "34", "pondicherry": "34",
    "andaman and nicobar islands": "35",
    "telangana": "36", "andhra pradesh": "37",
    "ladakh": "38", "other territory": "97",
}


def derive_state_code(
    explicit_state_code: Optional[str] = None,
    state_name: Optional[str] = None,
    gstin: Optional[str] = None,
) -> Optional[str]:
    """Best-effort 2-digit GST state code, in priority order (Part C):
      1. an explicit, valid state_code
      2. the GSTIN prefix (first two digits — the registered state, CGST Act §25)
      3. the state name mapped via INDIAN_STATE_CODES
      4. None (caller decides whether absence is an error)
    Pure and non-raising — derivation must never block provisioning.
    """
    if explicit_state_code:
        code = str(explicit_state_code).strip()
        if code in _VALID_STATE_CODES:
            return code
    if gstin:
        prefix = str(gstin).strip().upper()[:2]
        if prefix in _VALID_STATE_CODES:
            return prefix
    if state_name:
        code = INDIAN_STATE_CODES.get(str(state_name).strip().lower())
        if code:
            return code
    return None


def collect_errors(**fields: tuple) -> list[str]:
    """
    Run multiple validators and collect all error messages.
    Usage:
        errors = collect_errors(
            gstin=(validate_gstin, data.get("gstin")),
            pan=(validate_pan, data.get("pan")),
        )
    """
    errors = []
    for _field, (validator, value) in fields.items():
        err = validator(value)
        if err:
            errors.append(err)
    return errors
