"""The one place the API reaches Supabase Storage (POST-A-339, the Storage step).

WHAT THIS REPLACES
    Every route that stored, signed or removed a file did it with the REQUEST's own client (`get_supabase().storage`, which
    under USE_USER_JWT carries the caller's token), so that the policies of migrations 005 and 469 on `storage.objects` decided
    who could open which folder: the first folder is the caller's own firm, the second a client the caller is assigned to, and
    the verb needs a tier (a Partner to delete). That is a second place a rule about people lives, in SQL, for a thing the route
    has just decided in Python. It also meant a signed-in person with their own token could call Storage by hand and open or
    write whatever those policies allowed, when nothing legitimate needs that to work at all.

    There is one door now. It uses the SERVER's client, and it is BOUND TO A FOLDER: `storage_folder(bucket, firm, client)`
    answers an object that will upload, sign and remove keys under `{firm}/{client}/` and refuse any other. The route has
    already decided who the caller is and which client they may touch (`rbac()`, `assert_client_access`); the door is what makes
    the server's key unable to be used for anything outside the folder the route asserted, so a path read out of a row that a
    member could edit (a key column is writable over PostgREST by an Executive) can no longer name somebody else's object and be
    signed on the strength of a service key.

WHAT THE DOOR DOES NOT DO
    It does not decide who may write or read: that is the route's (`rbac()` and the client check), as it is for every other
    privileged query. It does not read a file, and it does not know a content type is acceptable: `core/uploads` decides that
    before the bytes get here. It does not retry.

THE FOLDER IS DATA, NOT A POLICY
    The layouts in use are `{firm}/{client}/...` (documents, notice attachments, bill and note attachments, the year-end packs),
    `shared_reports/{client}/...` (a report shared to the portal, signed by the server for a portal principal who has no policy
    to satisfy at all) and `logos/{firm}/...` (the firm's own logo, in a public bucket). Each is a constructor argument, so a
    new layout is a new line at its caller and not a new code path here.

THE LOOKUP IS AT CALL TIME, ON PURPOSE
    As in `core.db_provider`: the client is asked for when a method runs, so the suite can patch
    `core.supabase_client.get_service_supabase` and the next call sees the patch.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Optional

#: What one folder of a key may be made of. A whitelist, as `core.uploads.safe_path_segment` is: a blacklist of separators has to
#: anticipate every spelling of one. A UUID, a financial year and the literal folder names all satisfy it. It is the SAME pattern as
#: `core.uploads._SEGMENT` (a test holds the two equal), so a value the upload code let into a key is a value the door accepts.
_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}")


#: What no key may carry after the folder, whatever the route built it from. A key is opaque to Storage, so none of these climbs out
#: of anything there; they are refused because the Python client puts the key into the request's URL without encoding it: `?` and
#: `#` would cut the request short and name a different key, and a percent-encoded dot, slash or backslash is a separator in
#: disguise. Bidirectional controls make a name that reads as another one. A key this release builds is made of letters, digits
#: and `._- ` (`core.uploads.storage_name`), so none is refused (an older key holding `?` or `#` was never reachable under its own
#: name through that URL), and a key an older release stored with a `..` INSIDE a file name (`invoice..pdf`) is a name and not a
#: climb, so it is allowed.
_NEVER_IN_A_KEY = frozenset("\\?#\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
_ENCODED_SEPARATOR = re.compile(r"%(?:2e|2f|5c)", re.IGNORECASE)


class StoragePathRefused(Exception):
    """A key that is not under the folder the door was bound to. Carries no path: the caller says what it was doing."""


def _segment(value: object, what: str) -> str:
    text = "" if value is None else str(value)
    if not _SEGMENT.fullmatch(text) or ".." in text:
        raise StoragePathRefused(f"{what} is not a folder name")
    return text


class FolderStorage:
    """One bucket's keys under one folder, through the server's client."""

    __slots__ = ("bucket", "folder")

    def __init__(self, bucket: str, *segments: object):
        if not isinstance(bucket, str) or not _SEGMENT.fullmatch(bucket):
            raise StoragePathRefused("the bucket is not a bucket name")
        if not segments:
            raise StoragePathRefused("a door with no folder would open the whole bucket")
        self.bucket = bucket
        self.folder = "/".join(_segment(s, "a folder of the key") for s in segments) + "/"

    # ── the one rule ─────────────────────────────────────────────────────────────────────────────────────────────
    def owns(self, path: object) -> bool:
        """Whether a key sits under this folder: one or more non-empty path components after it, none of them `.` or `..` (an
        empty one is a doubled, leading or trailing separator), and no character `_NEVER_IN_A_KEY` names, no control character
        and no percent-encoded dot, slash or backslash."""
        if not isinstance(path, str) or not path.startswith(self.folder) or len(path) == len(self.folder):
            return False
        rest = path[len(self.folder):]
        return all(part not in ("", ".", "..") for part in rest.split("/")) \
            and not any(ch in _NEVER_IN_A_KEY or unicodedata.category(ch) == "Cc" for ch in rest) \
            and not _ENCODED_SEPARATOR.search(rest)

    def _own(self, path: object) -> str:
        if not self.owns(path):
            raise StoragePathRefused("the key is not under this folder")
        return path  # type: ignore[return-value]

    def _store(self):
        from core.supabase_client import get_service_supabase
        return get_service_supabase().storage.from_(self.bucket)

    # ── the verbs the routes use ───────────────────────────────────────────────────────────────────────────────────
    def upload(self, path: str, content: bytes, content_type: str, *, upsert: bool = False) -> Any:
        options: dict[str, str] = {"content-type": content_type}
        if upsert:
            options["upsert"] = "true"
        return self._store().upload(path=self._own(path), file=content, file_options=options)

    def create_signed_url(self, path: str, expires_in: int) -> Any:
        return self._store().create_signed_url(self._own(path), expires_in=expires_in)

    def create_signed_urls(self, paths: Iterable[str], expires_in: int) -> Any:
        return self._store().create_signed_urls([self._own(p) for p in paths], expires_in=expires_in)

    def remove(self, paths: Iterable[str]) -> Any:
        return self._store().remove([self._own(p) for p in paths])

    def get_public_url(self, path: str) -> Optional[str]:
        return self._store().get_public_url(self._own(path))


def storage_folder(bucket: str, *segments: object) -> FolderStorage:
    """The door to `bucket`, bound to the folder `segments` name (`storage_folder("Documents", firm_id, client_id)` is
    `Documents/{firm}/{client}/`). A segment that is not a plain folder name raises `StoragePathRefused` here, before any
    request is made."""
    return FolderStorage(bucket, *segments)
