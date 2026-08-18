"""Environment-driven security settings for the simulated development environment.

The JWT secret must always come from the environment and must never be
hardcoded or committed. All settings fail closed: a missing or invalid
secret prevents authentication entirely.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict

from arc.security.models import ApplicationRole

JWT_SECRET_MIN_LENGTH = 16


class SecurityConfigurationError(Exception):
    """Raised when the security configuration is missing or invalid."""


@dataclass(frozen=True)
class SecuritySettings:
    """Security configuration derived from the environment."""

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "arc"
    jwt_audience: str = "arc-api"
    jwt_expiry_seconds: int = 3600
    application_role_assignments: Dict[str, ApplicationRole] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.jwt_secret or len(self.jwt_secret) < JWT_SECRET_MIN_LENGTH:
            raise SecurityConfigurationError(
                f"JWT_SECRET must be set and at least {JWT_SECRET_MIN_LENGTH} characters long"
            )
        if self.jwt_algorithm != "HS256":
            raise SecurityConfigurationError("Only HS256 is supported")
        for user_id, role in self.application_role_assignments.items():
            if not isinstance(role, ApplicationRole):
                raise SecurityConfigurationError(
                    f"Invalid application role assignment for user {user_id}"
                )


def _parse_role_assignments(raw: str) -> Dict[str, ApplicationRole]:
    """Parse the APPLICATION_ROLE_ASSIGNMENTS JSON into role assignments.

    The value is a JSON object mapping user IDs to application role names,
    for example::

        {"user-1": "platform_administrator", "user-2": "operations_user"}

    Invalid or unknown values fail closed by raising a configuration error.
    """
    assignments: Dict[str, ApplicationRole] = {}
    if not raw:
        return assignments
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SecurityConfigurationError("APPLICATION_ROLE_ASSIGNMENTS must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise SecurityConfigurationError("APPLICATION_ROLE_ASSIGNMENTS must be a JSON object")
    for user_id, role_name in parsed.items():
        try:
            assignments[user_id] = ApplicationRole(role_name)
        except ValueError as exc:
            raise SecurityConfigurationError(
                f"Unknown application role for user {user_id}: {role_name}"
            ) from exc
    return assignments


def get_security_settings() -> SecuritySettings:
    """Build security settings from the environment.

    Role assignments default to an empty mapping, which means every user is
    denied by default (fail closed).
    """
    return SecuritySettings(
        jwt_secret=os.getenv("JWT_SECRET", ""),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        jwt_issuer=os.getenv("JWT_ISSUER", "arc"),
        jwt_audience=os.getenv("JWT_AUDIENCE", "arc-api"),
        jwt_expiry_seconds=int(os.getenv("JWT_EXPIRY_SECONDS", "3600")),
        application_role_assignments=_parse_role_assignments(
            os.getenv("APPLICATION_ROLE_ASSIGNMENTS", "")
        ),
    )
