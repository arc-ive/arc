"""Repository interfaces for Arc domain."""

from typing import List, Protocol

from arc.domain.models import ConnectorConfig, Membership, Skill, Tenant, User


class TenantRepository(Protocol):
    """Repository for Tenant entities."""

    async def create(self, tenant: Tenant) -> Tenant:
        """Create a new tenant."""
        ...

    async def get_by_id(self, tenant_id: str) -> Tenant:
        """Get tenant by ID."""
        ...

    async def exists(self, tenant_id: str) -> bool:
        """Check if tenant exists."""
        ...

    async def delete(self, tenant_id: str) -> None:
        """Delete tenant."""
        ...


class UserRepository(Protocol):
    """Repository for User entities."""

    async def create(self, user: User) -> User:
        """Create a new user."""
        ...

    async def get_by_id(self, user_id: str) -> User:
        """Get user by ID."""
        ...

    async def get_by_email(self, email: str) -> User:
        """Get user by email."""
        ...

    async def get_by_tenant(self, tenant_id: str) -> List[User]:
        """Get all users for a tenant."""
        ...

    async def exists(self, user_id: str) -> bool:
        """Check if user exists."""
        ...

    async def delete(self, user_id: str) -> None:
        """Delete user."""
        ...


class MembershipRepository(Protocol):
    """Repository for Membership entities."""

    async def create(self, membership: Membership) -> Membership:
        """Create a new membership."""
        ...

    async def get_by_user_and_tenant(self, user_id: str, tenant_id: str) -> Membership:
        """Get membership by user and tenant IDs."""
        ...

    async def exists(self, user_id: str, tenant_id: str) -> bool:
        """Check if membership exists."""
        ...

    async def delete(self, membership_id: str) -> None:
        """Delete membership."""
        ...

    async def get_tenants_for_user(self, user_id: str) -> List[Tenant]:
        """Get all tenants for a user."""
        ...

    async def get_users_for_tenant(self, tenant_id: str) -> List[User]:
        """Get all users for a tenant."""
        ...

    async def get_memberships_for_user(self, user_id: str) -> List[Membership]:
        """Get all memberships for a user."""
        ...

    async def get_memberships_for_tenant(self, tenant_id: str) -> List[Membership]:
        """Get all memberships for a tenant."""
        ...


class ConnectorRepository(Protocol):
    """Repository for ConnectorConfig entities."""

    async def create(self, connector: ConnectorConfig) -> ConnectorConfig:
        """Create a new connector configuration."""
        ...

    async def get_by_id(self, connector_id: str, tenant_id: str) -> ConnectorConfig:
        """Get a connector configuration by ID, scoped to a tenant."""
        ...

    async def list_for_tenant(self, tenant_id: str) -> List[ConnectorConfig]:
        """List all connector configurations for a tenant."""
        ...

    async def exists(self, connector_id: str, tenant_id: str) -> bool:
        """Check if a connector configuration exists within a tenant."""
        ...

    async def delete(self, connector_id: str, tenant_id: str) -> None:
        """Delete a connector configuration, scoped to a tenant."""
        ...


class SkillRepository(Protocol):
    """Repository for Skill entities."""

    async def create(self, skill: Skill) -> Skill:
        """Create a new skill."""
        ...

    async def get_by_id(self, skill_id: str, tenant_id: str) -> Skill:
        """Get a skill by ID, scoped to a tenant."""
        ...

    async def list_for_tenant(self, tenant_id: str) -> List[Skill]:
        """List all skills for a tenant."""
        ...

    async def exists(self, skill_id: str, tenant_id: str) -> bool:
        """Check if a skill exists within a tenant."""
        ...

    async def delete(self, skill_id: str, tenant_id: str) -> None:
        """Delete a skill, scoped to a tenant."""
        ...


class RepositoryFactory:
    """Factory for creating repository instances."""

    @staticmethod
    def create_tenancy_repositories(db_instance):
        """Create the tenancy repository instances for a database.

        Returns a list ordered as (tenant, user, membership) for direct use
        with ServiceFactory.create_domain_services.
        """
        from arc.repositories.tenancy import (
            PostgreSQLMembershipRepository,
            PostgreSQLTenantRepository,
            PostgreSQLUserRepository,
        )

        return [
            PostgreSQLTenantRepository(db_instance),
            PostgreSQLUserRepository(db_instance),
            PostgreSQLMembershipRepository(db_instance),
        ]
