"""Security audit logging — CSF 2.0 DE.CM / GV.OV.

Every security-relevant event (auth, privilege changes, deletions) is written
both to the structured AuditLog table (queryable via /admin/audit) and to the
Python logger "arrow.security" for external log aggregation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_log = logging.getLogger("arrow.security")


def log_event(
    db: "Session",
    event_type: str,
    *,
    outcome: str = "SUCCESS",
    operator_id: int | None = None,
    resource: str | None = None,
    ip_address: str | None = None,
    detail: str = "",
) -> None:
    """Record a security event to the audit log table and the security logger.

    event_type examples: LOGIN_SUCCESS, LOGIN_FAIL, REGISTER, REGISTER_ELEVATED,
                         OPERATOR_UPDATE, OPERATOR_DELETE, PASSWORD_RESET
    outcome: SUCCESS or FAILURE
    resource: dot-notated "type:id" e.g. "operator:5", "callsign:ALPHA-1"
    """
    from backend.storage.models import AuditLog

    entry = AuditLog(
        event_type=event_type,
        outcome=outcome,
        operator_id=operator_id,
        resource=resource,
        ip_address=ip_address,
        detail=detail,
    )
    db.add(entry)
    db.commit()

    level = logging.WARNING if outcome == "FAILURE" else logging.INFO
    _log.log(
        level,
        "AUDIT event=%s outcome=%s op_id=%s resource=%s ip=%s detail=%s",
        event_type, outcome, operator_id, resource, ip_address, detail,
    )
