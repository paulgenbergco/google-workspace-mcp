"""Shared helpers for the Google API wrappers.

Every ``.execute()`` in the g*.py wrappers passes ``num_retries=RETRIES`` so
googleapiclient retries with exponential backoff + jitter on the failures that
are worth retrying: 5xx, 429, and 403 when the reason is a rate limit. This
matters most for the cross-account fan-out tools, which fire the same request
once per configured account and are exactly the shape Google throttles.
"""

import json
from typing import Any, Optional

from googleapiclient.errors import HttpError

# Retries per request. 5 gives roughly 1+2+4+8+16s of backoff in the worst case.
RETRIES = 5


def http_status(exc: BaseException) -> Optional[int]:
    """HTTP status behind an HttpError, or None if it isn't one."""
    resp = getattr(exc, "resp", None)
    return getattr(resp, "status", None)


def describe_http_error(exc: HttpError) -> str:
    """Turn an HttpError into a one-line, readable message.

    googleapiclient's own str() embeds the full request URI, which buries the
    part that matters (status, reason, message) in noise.
    """
    status = http_status(exc) or "?"
    reason = ""
    message = ""

    content: Any = getattr(exc, "content", None)
    if content:
        try:
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            error = json.loads(content).get("error", {})
            message = error.get("message", "") or ""
            errors = error.get("errors") or []
            if errors and isinstance(errors, list):
                reason = errors[0].get("reason", "") or ""
            if not reason:
                reason = error.get("status", "") or ""
        except (ValueError, AttributeError, TypeError):
            message = str(content)[:200]

    parts = [f"HTTP {status}"]
    if reason:
        parts.append(reason)
    if message:
        parts.append(message)
    return ": ".join(parts)
