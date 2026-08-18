"""X-11 authentication and application RBAC.

Authentication establishes identity via JWT bearer tokens. Authorization is
enforced server-side through application roles and explicit permissions.

The application role system is completely separate from the X-10 tenant
membership roles (``arc.domain.models.UserRole``). There is NO mapping
between the two systems.
"""
