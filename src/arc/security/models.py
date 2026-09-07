"""X-11 security domain models.

``AuthenticatedPrincipal`` is the minimal stable identity contract consumed
by application services. It carries ONLY the user ID derived from the
validated JWT ``sub`` claim. It never carries roles, permissions, tenant
context, or JWT internals.

``ApplicationRole`` is the X-11 application role system. It is deliberately
separate from the X-10 membership ``UserRole`` (OWNER/MEMBER/VIEWER) and
must never be derived from or mapped to it.
"""

from dataclasses import dataclass
from enum import Enum


class ApplicationRole(str, Enum):
    """X-11 application roles.

    These are application-level roles. They are intentionally independent
    of the X-10 tenant membership roles (``UserRole``: OWNER/MEMBER/VIEWER).
    There is NO mapping between the two role systems.
    """

    PLATFORM_ADMINISTRATOR = "platform_administrator"
    COMPANY_ADMINISTRATOR = "company_administrator"
    OPERATIONS_USER = "operations_user"
    EMPLOYEE = "employee"
    WEBHOOK_PROCESSOR = "webhook_processor"


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Authenticated identity for a request.

    The ``user_id`` MUST come exclusively from the validated JWT ``sub``
    claim. It must never be derived from request bodies, query parameters,
    or arbitrary client headers.
    """

    user_id: str

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("Authenticated principal user_id cannot be empty")


@dataclass(frozen=True)
class Permission:
    """An explicit permission as a resource/action pair.

    The canonical string form is ``resource:action`` (for example
    ``tenant:read``).
    """

    resource: str
    action: str

    @property
    def value(self) -> str:
        return f"{self.resource}:{self.action}"

    def __str__(self) -> str:
        return self.value

    def __post_init__(self) -> None:
        if not self.resource:
            raise ValueError("Permission resource cannot be empty")
        if not self.action:
            raise ValueError("Permission action cannot be empty")
