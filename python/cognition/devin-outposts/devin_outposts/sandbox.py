"""Identify and inspect sandboxes across orchestrator restarts.

The ``devin-<safe session id>`` name and ``devin.session_id`` / ``devin.outpost_id``
labels are the reconciliation key linking queue entries to sandboxes.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Mapping

from .config import Config

try:
    from daytona import DaytonaError, DaytonaNotFoundError
except ImportError:
    try:
        from daytona.exceptions import DaytonaError, DaytonaNotFoundError
    except ImportError:

        class DaytonaError(Exception):
            pass

        class DaytonaNotFoundError(DaytonaError):
            pass


LOGGER = logging.getLogger(__name__)
SANDBOX_NAME_MAX_LENGTH = 63
SANDBOX_NAME_HASH_LENGTH = 24


def labels_for(config: Config, session_id: str) -> dict[str, str]:
    return {
        "devin.session_id": session_id,
        "devin.outpost_id": config.outpost_id,
    }


def sandbox_name_for(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[
        :SANDBOX_NAME_HASH_LENGTH
    ]
    readable_limit = SANDBOX_NAME_MAX_LENGTH - len("devin--") - len(digest)
    readable = safe_identifier(session_id)[:readable_limit].rstrip("-._") or "unknown"
    return f"devin-{readable}-{digest}"


def safe_identifier(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return safe or "unknown"


def sandbox_state(sandbox: Any) -> str:
    state = getattr(sandbox, "state", "")
    value = getattr(state, "value", state)
    return str(value or "").lower()


def sandbox_label(sandbox: Any, key: str) -> str | None:
    labels = getattr(sandbox, "labels", None) or {}
    if isinstance(labels, Mapping):
        value = labels.get(key)
        return str(value) if value is not None else None
    return None


def is_not_found(exc: BaseException) -> bool:
    if isinstance(exc, DaytonaNotFoundError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code == 404:
        return True
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) == 404:
        return True
    return exc.__class__.__name__ in {"NotFoundError", "NotFoundException"}
