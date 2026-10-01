"""The one place an uploaded file is read, sized, typed and named.

WHY THIS EXISTS (SECURITY-PRIVACY-20)
    Nine routes take an `UploadFile` and each had its own idea of what to do with
    it. Four (a client document, a debit-note attachment, a purchase-credit-note
    attachment, a shared report) did `content = file.file.read()` with no bound at
    all, two of those interpolated the caller's `filename` into the storage key
    with only "/" replaced, and the document route also interpolated the
    caller's `document_type` — a free string, although the database's own CHECK
    admits nine values. The other five capped the size AFTER reading: a 500 MB
    body was read whole into memory and then refused, which is the same exhaustion
    with a polite error at the end. On a 512 MB instance one request is enough.

    Cross-firm traversal was never the risk — Storage's firm-prefix policy holds —
    so what this closes is memory, odd keys inside the firm, and a file whose
    bytes are not what its name says.

WHAT IT DOES
    * `read_limited` reads AT MOST `max_bytes + 1` bytes and refuses with 413 the
      moment the file is over, so the memory a request can cost is decided here
      and not by its sender. The body-size middleware in front of the app
      (`middleware/body_limit.py`) is the other half: it refuses an oversized
      request before the multipart parser spools it to disk.
    * `accept_upload` is that plus an EXTENSION ALLOWLIST, a check that the bytes
      look like what the extension claims (so an `.exe` renamed `.pdf` is 415, not
      stored), and a content type chosen BY US from the extension. The caller's
      `Content-Type` is never trusted and never stored: it is a header the sender
      writes, and a stored `text/html` is what makes a file render in a browser.
    * `display_name` (what a CA sees, Unicode kept) and `storage_name` (ASCII, what
      goes in the key) are separate, because Storage keys are a worse place for
      "चालान.pdf" than a column is. Neither can contain a separator, a control
      character or a leading dot.
    * `safe_path_segment` refuses a value that would be interpolated into a key as
      a folder — a separator, `..`, control characters, anything over 64 chars.

WHAT IT DELIBERATELY DOES NOT DO
    * It does not scan for malware. Nothing here opens or executes a file, and
      stored objects are served with OUR content type from a different origin.
    * SVG, HTML and XML are not on the allowlist: each can carry script and each is
      rendered, not downloaded, by a browser. (The firm logo route has its own
      image rules and is the one place SVG is accepted.)
    * It does not know what a caller wants to DO with the bytes. A route with a
      narrower rule (a statement is CSV/XLSX/PDF; a shared report is `.xlsx`) asks
      for a narrower `allowed` set or sniffs the bytes itself with `looks_like`.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

from fastapi import HTTPException

MB = 1024 * 1024
#: What a document or an attachment may weigh. The same 10 MB bank statements and
#: AI extraction already use, so one number answers "how big may a file be here".
DEFAULT_MAX_BYTES = 10 * MB


class UploadRejected(HTTPException):
    """A refused upload: 413 too large, 415 wrong kind, 422 unusable name or field.

    An `HTTPException` so FastAPI answers it as a status code wherever it is
    raised — including from a route that wraps its body in a broad `except
    Exception`, which must re-raise `HTTPException` (the note routes do).
    """


# ── type table ───────────────────────────────────────────────────────────────
# extension -> (the content type WE store it under, how its bytes are recognised)
#
# "binary" signatures are matched at the start of the file (PDF within the first
# KiB, which the format allows); "text" types have no magic number, so they are
# held to "no NUL byte in the first 8 KiB" — enough to refuse a renamed binary.
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_TYPES: dict[str, tuple[str, str]] = {
    "pdf":  ("application/pdf", "pdf"),
    "png":  ("image/png", "png"),
    "jpg":  ("image/jpeg", "jpeg"),
    "jpeg": ("image/jpeg", "jpeg"),
    "gif":  ("image/gif", "gif"),
    "webp": ("image/webp", "webp"),
    "tif":  ("image/tiff", "tiff"),
    "tiff": ("image/tiff", "tiff"),
    # What a phone camera saves by default.
    "heic": ("image/heic", "heif"),
    "heif": ("image/heif", "heif"),
    "xlsx": (_XLSX, "zip"),
    "docx": (_DOCX, "zip"),
    "zip":  ("application/zip", "zip"),
    "xls":  ("application/vnd.ms-excel", "ole"),
    "doc":  ("application/msword", "ole"),
    "csv":  ("text/csv", "text"),
    "txt":  ("text/plain", "text"),
    "json": ("application/json", "text"),
}

#: What a client document or an attachment to a note may be.
ATTACHMENT_TYPES = frozenset(_TYPES)


def _is_webp(head: bytes) -> bool:
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


_SIGNATURES = {
    "pdf":  lambda h: b"%PDF-" in h[:1024],
    "png":  lambda h: h[:8] == b"\x89PNG\r\n\x1a\n",
    "jpeg": lambda h: h[:3] == b"\xff\xd8\xff",
    "gif":  lambda h: h[:6] in (b"GIF87a", b"GIF89a"),
    "webp": _is_webp,
    "tiff": lambda h: h[:4] in (b"II*\x00", b"MM\x00*"),
    "heif": lambda h: h[4:8] == b"ftyp",
    "zip":  lambda h: h[:4] in (b"PK\x03\x04", b"PK\x05\x06"),
    "ole":  lambda h: h[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    "text": lambda h: b"\x00" not in h[:8192],
}

#: Binary formats recognisable from the bytes alone, for a file with no extension.
#: A zip container is deliberately absent: an `.xlsx` and a `.zip` are the same
#: bytes, so "what is this" has no answer and the caller is asked to name it.
_BY_SIGNATURE = ("pdf", "png", "jpeg", "gif", "webp", "tiff", "heif")
_EXT_OF_SIGNATURE = {"pdf": "pdf", "png": "png", "jpeg": "jpg", "gif": "gif",
                     "webp": "webp", "tiff": "tiff", "heif": "heic"}


def looks_like(extension: str, content: bytes) -> bool:
    """Whether `content`'s bytes are plausibly a file of this extension."""
    entry = _TYPES.get(extension.lower().lstrip("."))
    return bool(entry) and _SIGNATURES[entry[1]](content)


# ── reading ──────────────────────────────────────────────────────────────────

def read_limited(file, max_bytes: int = DEFAULT_MAX_BYTES, *, message: Optional[str] = None) -> bytes:
    """The file's bytes, reading at most `max_bytes + 1` of them.

    413 the moment the file is over. The `size` Starlette records after parsing
    the multipart body is checked first, so a file already known to be too large
    is refused without reading a byte of it.
    """
    detail = message or f"File too large (max {max_bytes // MB} MB)."
    declared = getattr(file, "size", None)
    if isinstance(declared, int) and declared > max_bytes:
        raise UploadRejected(status_code=413, detail=detail)
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UploadRejected(status_code=413, detail=detail)
    return data


# ── naming ───────────────────────────────────────────────────────────────────
_NAME_CAP = 100
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2066-\u2069\ufeff]")
_STORAGE_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _basename(raw: str) -> str:
    # Both separators: a Windows path arrives as `C:\Users\x\scan.pdf`.
    return re.split(r"[\\/]", raw or "")[-1]


def split_extension(raw_name: str) -> tuple[str, str]:
    """(stem, lower-case extension without the dot) of a caller-supplied name."""
    base = _basename(_CONTROL.sub("", unicodedata.normalize("NFKC", raw_name or ""))).strip()
    stem, dot, ext = base.rpartition(".")
    if not dot or not stem:
        return base, ""
    return stem, ext.strip().lower()


def _keep_for_display(ch: str) -> str:
    """A letter, mark or number of ANY script, or one of a few separators.

    By Unicode CATEGORY and not by `\\w`: Devanagari vowel signs (ा, ि, ु ...)
    are combining marks, which `\\w` does not match, so a regex would turn
    "चालान.pdf" into "च_ल_न.pdf" — for a product whose users name files in Hindi,
    Gujarati and Tamil that is a real loss, and nothing about a mark is unsafe.
    """
    if unicodedata.category(ch)[0] in "LMN" or ch in ".- ()_":
        return ch
    return "_"


def _tidy(stem: str, cap: int, *, ascii_only: bool) -> str:
    if ascii_only:
        stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
        cleaned = _STORAGE_UNSAFE.sub("_", stem)
    else:
        cleaned = "".join(_keep_for_display(ch) for ch in stem)
    cleaned = re.sub(r"\.{2,}", ".", cleaned)            # no `..` anywhere in a name
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip(" ._-")
    return cleaned[:cap].strip(" ._-") or "upload"


def display_name(raw_name: str, extension: str) -> str:
    """What the CA sees: any script kept, no separator, no control character."""
    stem, _ = split_extension(raw_name)
    tidy = _tidy(stem, _NAME_CAP, ascii_only=False)
    return f"{tidy}.{extension}" if extension else tidy


def storage_name(raw_name: str, extension: str) -> str:
    """What goes in the storage key: ASCII only, no separator, never leading `.`."""
    stem, _ = split_extension(raw_name)
    tidy = _tidy(stem, _NAME_CAP, ascii_only=True)
    return f"{tidy}.{extension}" if extension else tidy


_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}")


def safe_path_segment(value: object, *, field: str) -> str:
    """A value that is about to become ONE folder of a storage key, or 422.

    A whitelist, not a blacklist of `../`: a blacklist has to anticipate every
    encoding of a separator, and this only has to keep what a folder name needs.
    Refuses a separator, a leading dot or dash, `..`, control characters and more
    than 64 characters. Returns the value unchanged when it passes.
    """
    text = "" if value is None else str(value)
    if not _SEGMENT.fullmatch(text) or ".." in text:
        raise UploadRejected(
            status_code=422,
            detail=f"{field} is not a valid value (letters, digits, space, '.', '-' and '_' "
                   "only, up to 64 characters).")
    return text


# ── the whole decision ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class AcceptedUpload:
    content: bytes
    extension: str
    #: Chosen by us from the extension — never the caller's Content-Type.
    content_type: str
    #: For the CA to read. Unicode kept.
    display_name: str
    #: For the storage key. ASCII only.
    storage_name: str


def accept_upload(
    file,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allowed: Iterable[str] = ATTACHMENT_TYPES,
    message: Optional[str] = None,
) -> AcceptedUpload:
    """Read, size, type and name one uploaded file — or raise `UploadRejected`.

    Order matters: size first (it is the cheapest refusal and the one that
    protects memory), then the extension, then the bytes, so the error a person
    sees is the first thing they can act on.
    """
    content = read_limited(file, max_bytes, message=message)
    allowed_set = {a.lower().lstrip(".") for a in allowed}

    _, ext = split_extension(getattr(file, "filename", None) or "")
    if not ext:
        # No extension at all (a phone "scan", a share-sheet export): take what the
        # BYTES say, for the formats that can say it.
        ext = next((_EXT_OF_SIGNATURE[k] for k in _BY_SIGNATURE if _SIGNATURES[k](content)), "")
    if ext not in _TYPES or ext not in allowed_set:
        shown = ", ".join(f".{e}" for e in sorted(allowed_set & set(_TYPES)))
        raise UploadRejected(
            status_code=415,
            detail=f"That kind of file cannot be uploaded here. Accepted: {shown}.")
    if not looks_like(ext, content):
        raise UploadRejected(
            status_code=415,
            detail=f"The contents of that file are not a valid .{ext} — rename or re-save it "
                   "and try again.")

    raw = getattr(file, "filename", None) or "upload"
    return AcceptedUpload(
        content=content,
        extension=ext,
        content_type=_TYPES[ext][0],
        display_name=display_name(raw, ext),
        storage_name=storage_name(raw, ext),
    )
