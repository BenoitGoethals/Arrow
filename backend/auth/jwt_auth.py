"""Compatibility re-exports.

The auth module was split into domain/application/infrastructure/presentation
layers. Many call sites import from `backend.auth.jwt_auth` directly; this
module keeps those imports working by re-exporting the public surface.

New code should import from the specific layer:
- `backend.auth.dependencies`           for get_current_operator / require_role
- `backend.auth.infrastructure.token_service`     for JWT functions
- `backend.auth.infrastructure.password_hasher`   for password functions
"""

from __future__ import annotations

from backend.auth.dependencies import (
    get_current_operator,
    oauth2_scheme,
    require_role,
)
from backend.auth.infrastructure.password_hasher import (
    hash_password,
    verify_password,
)
from backend.auth.infrastructure.token_service import (
    create_access_token,
    create_mfa_session,
    decode_token,
)

__all__ = [
    "create_access_token",
    "create_mfa_session",
    "decode_token",
    "get_current_operator",
    "hash_password",
    "oauth2_scheme",
    "require_role",
    "verify_password",
]
