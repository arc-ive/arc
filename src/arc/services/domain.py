"""Domain services for Arc multi-tenant foundation."""

from typing import List, Tuple

from arc.db.connection import NotFoundError
from arc.domain.models import Membership, Tenant, TenantContext, User, UserRole
from arc.repositories import MembershipRepository, TenantRepository, UserRepository


class TenantService:
    """Domain service for tenant operations."""

    def __init__(self, tenant_repo: TenantRepository):
        self.tenant_repo = tenant_repo

    async def create_tenant(self, tenant: Tenant) -> Tenant:
        """Create a new tenant."""
        if not tenant.id:
            raise ValueError("Tenant ID cannot be empty")
        if not tenant.name:
            raise ValueError("Tenant name cannot be empty")
        return await self.tenant_repo.create(tenant)

    async def create_tenant_with_owner(self, tenant: Tenant, user_id: str) -> Tenant:
        """Create a new tenant with an initial OWNER membership for the creator.

        The tenant and membership are created atomically: if either
        operation fails, both are rolled back.
        """
        if not tenant.id:
            raise ValueError("Tenant ID cannot be empty")
        if not tenant.name:
            raise ValueError("Tenant name cannot be empty")
        if not user_id:
            raise ValueError("User ID cannot be empty")

        import uuid
        from datetime import datetime, timezone

        membership = Membership(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tenant_id=tenant.id,
            role=UserRole.OWNER,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        return await self.tenant_repo.create_with_owner(tenant, membership)

    async def get_tenant(self, tenant_id: str) -> Tenant:
        """Get tenant by ID."""
        return await self.tenant_repo.get_by_id(tenant_id)

    async def list_all_tenants(self) -> List[Tenant]:
        """List all tenants (platform administrator operation)."""
        return await self.tenant_repo.list_all()

    async def list_all_tenants_paginated(self, limit: int, offset: int) -> Tuple[List[Tenant], int]:
        """List tenants with LIMIT/OFFSET and total count."""
        return await self.tenant_repo.list_all_paginated(limit, offset)

    async def set_tenant_status(self, tenant_id: str, new_status: str) -> Tenant:
        """Suspend or restore a tenant (ADR-011).

        Lossless and reversible: nothing is removed, and restoring
        returns the tenant to exactly its prior state. Deletion is
        deliberately not offered -- approval_requests and
        api_request_records both cascade from tenants, so removing the
        row would destroy the audit trail of a departed customer, which
        is usually the moment it is most needed.
        """
        # A targeted single-column write, not read-modify-write. Reading
        # the row and writing it back writes EVERY column, so a
        # concurrent profile edit and a suspension silently overwrite
        # each other -- and the direction that matters is losing the
        # suspension, leaving an operator believing a customer is
        # stopped when they are not.
        return await self.tenant_repo.set_status(tenant_id, new_status)

    async def update_tenant(self, tenant: Tenant) -> Tenant:
        """Update tenant company configuration."""
        if not tenant.id:
            raise ValueError("Tenant ID cannot be empty")
        if not tenant.name:
            raise ValueError("Tenant name cannot be empty")
        return await self.tenant_repo.update(tenant)

    async def tenant_exists(self, tenant_id: str) -> bool:
        """Check if tenant exists."""
        return await self.tenant_repo.exists(tenant_id)


class UserService:
    """Domain service for user operations."""

    def __init__(
        self,
        user_repo: UserRepository,
        membership_repo: MembershipRepository,
        tenant_repo: TenantRepository,
    ):
        self.user_repo = user_repo
        self.membership_repo = membership_repo
        self.tenant_repo = tenant_repo

    async def create_user(self, user: User) -> User:
        """Create a new user."""
        if not user.id:
            raise ValueError("User ID cannot be empty")
        if not user.email:
            raise ValueError("User email cannot be empty")
        return await self.user_repo.create(user)

    async def get_user(self, user_id: str) -> User:
        """Get user by ID."""
        return await self.user_repo.get_by_id(user_id)

    async def get_user_by_email(self, email: str) -> User:
        """Get user by email."""
        return await self.user_repo.get_by_email(email)

    async def associate_user_with_tenant(
        self,
        user_id: str,
        tenant_id: str,
        role: UserRole = UserRole.MEMBER,
        membership_id: str = None,
    ) -> Membership:
        """Associate a user with a tenant."""
        if not await self.user_repo.exists(user_id):
            raise ValueError(f"User with id {user_id} does not exist")

        if not await self.tenant_repo.exists(tenant_id):
            raise ValueError(f"Tenant with id {tenant_id} does not exist")

        if await self.membership_repo.exists(user_id, tenant_id):
            raise ValueError(f"User {user_id} already belongs to tenant {tenant_id}")

        import uuid

        if not membership_id:
            membership_id = str(uuid.uuid4())

        membership = Membership(id=membership_id, user_id=user_id, tenant_id=tenant_id, role=role)
        return await self.membership_repo.create(membership)

    async def get_users_for_tenant(self, tenant_id: str) -> List[User]:
        """Get all users for a tenant."""
        return await self.user_repo.get_by_tenant(tenant_id)

    async def get_users_for_tenant_paginated(
        self, tenant_id: str, limit: int, offset: int
    ) -> Tuple[List[User], int]:
        """Get users for a tenant with LIMIT/OFFSET and total count."""
        return await self.user_repo.get_by_tenant_paginated(tenant_id, limit, offset)

    async def list_all_users(self) -> List[User]:
        """List all users (platform administrator operation)."""
        return await self.user_repo.list_all()

    async def list_all_users_paginated(self, limit: int, offset: int) -> Tuple[List[User], int]:
        """List all users with LIMIT/OFFSET and total count."""
        return await self.user_repo.list_all_paginated(limit, offset)


# A tenant is usable only when its status is exactly this. Anything else
# -- suspended, an unrecognised value, a future state -- denies access.
TENANT_STATUS_ACTIVE = "active"


class TenantSuspendedError(Exception):
    """Raised when a trusted context is requested for a non-active tenant.

    Distinct from NotFoundError so the API can answer correctly: the
    tenant exists and the membership is real, but access is withdrawn.
    """


class MembershipService:
    """Domain service for membership operations."""

    def __init__(self, membership_repo: MembershipRepository):
        self.membership_repo = membership_repo

    async def create_membership(self, membership: Membership) -> Membership:
        """Create a new membership."""
        if not membership.id:
            import uuid

            membership.id = str(uuid.uuid4())

        if not membership.user_id:
            raise ValueError("User ID cannot be empty")

        if not membership.tenant_id:
            raise ValueError("Tenant ID cannot be empty")

        if membership.role not in [UserRole.OWNER, UserRole.MEMBER, UserRole.VIEWER]:
            raise ValueError(f"Invalid role: {membership.role}")

        return await self.membership_repo.create(membership)

    async def memberships_by_user(self, user_ids: list) -> dict:
        """Map user ids to their memberships, with tenant names.

        One query for a whole page rather than one per user: the platform
        directory renders every provisioned user, so a per-user lookup is
        an N+1 that grows with the customer base.

        Membership is platform administration metadata, not tenant
        content. ADR-008 already allows a PLATFORM_ADMINISTRATOR to
        create memberships for any user in any tenant, so reading which
        ones exist is strictly less privileged. Tenant content --
        knowledge, approvals, skills -- stays unreachable from the
        platform plane.
        """
        return await self.membership_repo.get_memberships_with_tenant_for_users(user_ids)

    async def remove_preserving_last_owner(self, user_id: str, tenant_id: str) -> str:
        """Remove a membership, never leaving the tenant without an owner.

        Returns ``"removed"``, ``"not_found"`` or ``"last_owner"``.

        Deliberately ONE call rather than a separate check and delete.
        The earlier shape -- is_last_owner() followed by
        remove_membership() -- was a time-of-check-to-time-of-use race
        with a real bypass: two owners removing each other concurrently
        each saw two owners, both deletes proceeded, and the tenant was
        left with none. Blocking self-removal did not prevent it, because
        neither admin removed themselves.

        A workspace with no owner cannot be administered by anyone in it;
        recovering one needs the platform operator. The guarantee is
        enforced under a row lock in the repository (ADR-009).
        """
        return await self.membership_repo.remove_membership_preserving_last_owner(
            user_id, tenant_id
        )

    async def get_membership(self, user_id: str, tenant_id: str) -> Membership:
        """Get membership by user and tenant IDs."""
        return await self.membership_repo.get_by_user_and_tenant(user_id, tenant_id)

    async def membership_exists(self, user_id: str, tenant_id: str) -> bool:
        """Check if membership exists."""
        return await self.membership_repo.exists(user_id, tenant_id)

    async def get_tenants_for_user(self, user_id: str) -> List[Tenant]:
        """Get all tenants for a user."""
        return await self.membership_repo.get_tenants_for_user(user_id)

    async def get_tenants_for_user_paginated(
        self, user_id: str, limit: int, offset: int
    ) -> Tuple[List[Tenant], int]:
        """Get tenants for a user with LIMIT/OFFSET and total count."""
        return await self.membership_repo.get_tenants_for_user_paginated(user_id, limit, offset)

    async def get_users_for_tenant(self, tenant_id: str) -> List[User]:
        """Get all users for a tenant."""
        return await self.membership_repo.get_users_for_tenant(tenant_id)

    async def get_memberships_for_user(self, user_id: str) -> List[Membership]:
        """Get all memberships for a user."""
        return await self.membership_repo.get_memberships_for_user(user_id)

    async def get_memberships_for_tenant(self, tenant_id: str) -> List[Membership]:
        """Get all memberships for a tenant."""
        return await self.membership_repo.get_memberships_for_tenant(tenant_id)

    async def remove_membership(self, user_id: str, tenant_id: str) -> None:
        """Remove a user's membership from a tenant.

        Args:
            user_id: The user whose membership to remove.
            tenant_id: The tenant from which to remove the membership.

        Raises:
            ValueError: If the membership does not exist.
        """
        try:
            membership = await self.membership_repo.get_by_user_and_tenant(user_id, tenant_id)
        except NotFoundError:
            raise ValueError(f"No membership found for user {user_id} in tenant {tenant_id}")
        await self.membership_repo.delete(membership.id)


class TenantContextService:
    """Service for managing tenant context."""

    def __init__(
        self,
        user_repo: UserRepository,
        tenant_repo: TenantRepository,
        membership_repo: MembershipRepository,
    ):
        self.user_repo = user_repo
        self.tenant_repo = tenant_repo
        self.membership_repo = membership_repo

    async def create_tenant_context(
        self,
        tenant_id: str,
        user_id: str,
    ) -> TenantContext:
        """Create a trusted tenant context.

        A trusted context requires a verified User-Tenant Membership.
        The persisted Membership.role is the authoritative role and is
        never taken from caller input.

        Args:
            tenant_id: The requested tenant ID.
            user_id: The authenticated user ID.

        Returns:
            TenantContext derived from the verified membership.

        Raises:
            ValueError: If tenant_id or user_id is empty.
            NotFoundError: If the tenant, user, or membership does not exist.
            TenantSuspendedError: If the tenant is not active (ADR-011).
        """
        if not tenant_id:
            raise ValueError("Tenant ID cannot be empty in context")

        if not user_id:
            raise ValueError("User ID cannot be empty in context")

        tenant = await self.tenant_repo.get_by_id(tenant_id)

        # Suspension is enforced here, and only here, because every
        # tenant-scoped route establishes a context before doing anything
        # (ADR-011). That covers routes which do not exist yet, rather
        # than being a check each new endpoint has to remember.
        #
        # Fail closed on anything that is not explicitly active: a tenant
        # is usable only when its status says so, so an unrecognised or
        # unreadable value denies rather than admits.
        if tenant.status != TENANT_STATUS_ACTIVE:
            raise TenantSuspendedError(f"Tenant {tenant_id} is not active and cannot be accessed")

        await self.user_repo.get_by_id(user_id)

        membership = await self.membership_repo.get_by_user_and_tenant(user_id, tenant_id)

        return TenantContext(
            tenant_id=membership.tenant_id,
            tenant_name=tenant.name,
            user_id=membership.user_id,
            role=membership.role,
        )

    async def validate_context(self, context: TenantContext) -> bool:
        """Validate a tenant context.

        A context is valid only when a verified membership exists for the
        context's user/tenant pair and the membership's persisted values
        match the context.

        Args:
            context: The TenantContext to validate.

        Returns:
            True if the context matches a verified membership, False otherwise.
        """
        if not context.is_valid:
            return False

        if not await self.tenant_repo.exists(context.tenant_id):
            return False

        if not await self.user_repo.exists(context.user_id):
            return False

        try:
            membership = await self.membership_repo.get_by_user_and_tenant(
                context.user_id, context.tenant_id
            )
        except NotFoundError:
            return False

        if membership is None:
            return False

        return (
            membership.user_id == context.user_id
            and membership.tenant_id == context.tenant_id
            and membership.role == context.role
        )


class ServiceFactory:
    """Factory for creating service instances."""

    @staticmethod
    def create_domain_services(repositories):
        """Create domain service instances."""
        tenant_repo, user_repo, membership_repo = repositories

        return {
            "tenant_service": TenantService(tenant_repo),
            "user_service": UserService(user_repo, membership_repo, tenant_repo),
            "membership_service": MembershipService(membership_repo),
            "tenant_context_service": TenantContextService(user_repo, tenant_repo, membership_repo),
        }
