"""
Supabase client for the FastAPI backend.
Uses SERVICE_ROLE key — full DB access, bypasses RLS for internal operations.
All tenant isolation enforced at repository level via firm_id filter.
"""
import os
import logging
from supabase import create_client, Client

_client: Client | None = None
_logger = logging.getLogger("caflow.supabase")


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set."
            )
        # Service role keys always start with "eyJ" (JWT) and are much longer
        # than anon keys. Log a warning if the key looks wrong.
        if not key.startswith("eyJ"):
            _logger.warning(
                "SUPABASE_SERVICE_ROLE_KEY does not look like a JWT "
                "(expected 'eyJ...'). Check Render env var value."
            )
        _logger.info(
            "Initialising Supabase client — URL: %s, key prefix: %s...",
            url,
            key[:12],
        )
        _client = create_client(url, key)
    return _client
