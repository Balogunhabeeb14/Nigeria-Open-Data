"""Access control and input checks for the pipeline API.

Reading published data is open. Everything that changes the platform
(registering a publisher or source, uploading a file, starting ingestion)
needs the admin token, and is switched off altogether until one is set.
"""
from __future__ import annotations

import hmac
import re
from pathlib import PurePath

from fastapi import Header, HTTPException

from pipeline.settings import settings

# Code a registered source may point at. A source names its connector and
# transform by dotted path and the worker imports them, so anything outside
# these packages must never be accepted from the API.
_ALLOWED_PREFIXES = ("pipeline.connectors.", "pipeline.transforms.")
_DOTTED_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()-]{0,150}$")
UPLOAD_EXTENSIONS = frozenset({".csv", ".xlsx", ".xls", ".pdf"})
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """FastAPI dependency: allow the request only with the admin token."""
    expected = settings.admin_token()
    if expected is None:
        raise HTTPException(
            status_code=503,
            detail="Admin endpoints are switched off. Set ADMIN_API_TOKEN on the server to enable them.",
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Missing or wrong X-Admin-Token header.")


def check_code_path(value: str, kind: str) -> str:
    """Accept only connectors and transforms that ship with the pipeline."""
    if not _DOTTED_PATH.match(value) or not value.startswith(_ALLOWED_PREFIXES):
        raise HTTPException(
            status_code=422,
            detail=f"{kind} must be a module path under pipeline.connectors or pipeline.transforms.",
        )
    return value


def check_identifier(value: str, kind: str) -> str:
    """Ids become folder names and URL parts: letters, digits, '-' and '_' only."""
    if not _SAFE_ID.match(value):
        raise HTTPException(
            status_code=422,
            detail=f"{kind} may contain only letters, digits, '-' and '_' (up to 64 characters).",
        )
    return value


def check_upload_name(filename: str | None) -> str:
    """Return a safe bare filename, or refuse the upload.

    The name is used as given by the client, so it is reduced to its last
    path component and must not be able to climb out of the landing folder.
    """
    name = PurePath((filename or "").replace("\\", "/")).name
    if not name or name.startswith(".") or not _SAFE_FILENAME.match(name):
        raise HTTPException(status_code=422, detail="File name is missing or contains unsupported characters.")
    if PurePath(name).suffix.lower() not in UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(UPLOAD_EXTENSIONS))}.",
        )
    return name
