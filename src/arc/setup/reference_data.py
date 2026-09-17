"""Production-like reference data provisioning for Arc.

Seeds a realistic multi-tenant reference environment on application startup.
Uses ``INSERT ... SELECT ... WHERE NOT EXISTS`` for full idempotency: running
provisioning multiple times against the same database produces no duplicates.

Reference environment:

- 4 tenants (Acme Technologies, Nova Systems, Vertex Solutions, Northstar Digital)
- 1 platform administrator (global, no tenant membership required)
- 16 tenant users (4 per tenant: company admin, ops user, 2 employees)
- 17 memberships linking tenant users to their tenants
- 2 connectors per tenant (GitHub + Slack)
- 2 knowledge documents per tenant
- 1 skill per tenant

Application roles (ApplicationRole) are configured separately via the
``APPLICATION_ROLE_ASSIGNMENTS`` environment variable and are NOT seeded
here. See ``.env.example`` for the required configuration.

This module is imported by ``Application._seed_bootstrap_data()`` and
executed at application startup. It must never be exposed through an API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg


# ---------------------------------------------------------------------------
# Reference data definitions
# ---------------------------------------------------------------------------

_TENANTS = [
    {
        "id": "ref-acme-technologies",
        "name": "Acme Technologies",
        "industry": "Technology",
        "website": "https://acme-tech.example.com",
    },
    {
        "id": "ref-nova-systems",
        "name": "Nova Systems",
        "industry": "Consulting",
        "website": "https://nova-systems.example.com",
    },
    {
        "id": "ref-vertex-solutions",
        "name": "Vertex Solutions",
        "industry": "Financial Services",
        "website": "https://vertex-solutions.example.com",
    },
    {
        "id": "ref-northstar-digital",
        "name": "Northstar Digital",
        "industry": "Marketing",
        "website": "https://northstar-digital.example.com",
    },
]

# Platform administrator: global role, no tenant membership.
_PLATFORM_ADMIN = {
    "id": "ref-platform-admin",
    "email": "platform-admin@arc-reference.example.com",
    "username": "Platform Administrator",
}

# Tenant users: (user_id_suffix, email, username, membership_role, application_role_hint)
# application_role_hint is for documentation only; actual assignment is via env var.
_TENANT_USERS = [
    ("company-admin", "company-admin", "owner", "company_administrator"),
    ("ops-user", "ops-user", "member", "operations_user"),
    ("employee-1", "employee-1", "member", "employee"),
    ("employee-2", "employee-2", "viewer", "employee"),
]

# Connector configurations per tenant.
_CONNECTORS = [
    {
        "provider": "github",
        "name": "GitHub Repository",
        "target": "acme-org/main-repo",
    },
    {
        "provider": "slack",
        "name": "Slack Workspace",
        "target": "general",
    },
]

# Knowledge documents per tenant.
_KNOWLEDGE_DOCUMENTS = [
    {
        "source": "policy",
        "external_id_suffix": "employee-handbook",
        "provenance": "Acme Technologies Employee Handbook v2.1",
        "content": (
            "This document outlines the employee handbook for Acme Technologies. "
            "It covers workplace policies, code of conduct, benefits, and "
            "operational guidelines. All employees are expected to review and "
            "acknowledge this handbook during onboarding."
        ),
    },
    {
        "source": "procedure",
        "external_id_suffix": "it-service-guide",
        "provenance": "Acme Technologies IT Service Guide",
        "content": (
            "IT Service Guide for Acme Technologies. This document provides "
            "procedures for requesting hardware, software access, VPN setup, "
            "and troubleshooting common technical issues. Contact the IT help "
            "desk for escalation."
        ),
    },
]

# Skills per tenant.
_SKILLS = [
    {
        "name": "Incident Response",
        "purpose": "Coordinate incident response workflow for critical service disruptions",
        "definition": {
            "inputs": ["incident_description", "severity_level"],
            "preconditions": ["user_has_incident_response_permission"],
            "steps": [
                "Validate incident severity and classification",
                "Notify on-call engineering team",
                "Create incident ticket and assign owner",
                "Monitor resolution progress",
                "Generate post-incident report",
            ],
            "constraints": [
                "Must not modify production data directly",
                "All actions must be logged for audit trail",
            ],
            "allowed_tools": ["check_service_health"],
            "approval_required": False,
            "expected_output": "Incident ticket created and team notified",
            "failure_behavior": "Log error and escalate to platform administrator",
            "risk": "medium",
        },
    },
]


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------


def _insert_tenant_sql(tenant: dict) -> str:
    return f"""
    INSERT INTO tenants (id, name, status, industry, website, created_at, updated_at)
    SELECT
        '{tenant["id"]}',
        '{tenant["name"]}',
        'active',
        '{tenant["industry"]}',
        '{tenant["website"]}',
        NOW(),
        NOW()
    WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE id = '{tenant["id"]}')
    """


def _insert_user_sql(user: dict) -> str:
    return f"""
    INSERT INTO users (id, email, username, status, created_at, updated_at)
    SELECT
        '{user["id"]}',
        '{user["email"]}',
        '{user["username"]}',
        'active',
        NOW(),
        NOW()
    WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = '{user["id"]}')
    """


def _insert_membership_sql(membership: dict) -> str:
    return f"""
    INSERT INTO memberships (id, user_id, tenant_id, role, created_at, updated_at)
    SELECT
        '{membership["id"]}',
        '{membership["user_id"]}',
        '{membership["tenant_id"]}',
        '{membership["role"]}',
        NOW(),
        NOW()
    WHERE NOT EXISTS (
        SELECT 1 FROM memberships
        WHERE user_id = '{membership["user_id"]}' AND tenant_id = '{membership["tenant_id"]}'
    )
    """


def _insert_connector_sql(connector: dict) -> str:
    return f"""
    INSERT INTO connector_configs
        (id, tenant_id, provider, name, target, status, created_at, updated_at)
    SELECT
        '{connector["id"]}',
        '{connector["tenant_id"]}',
        '{connector["provider"]}',
        '{connector["name"]}',
        '{connector["target"]}',
        'active',
        NOW(),
        NOW()
    WHERE NOT EXISTS (
        SELECT 1 FROM connector_configs
        WHERE tenant_id = '{connector["tenant_id"]}'
          AND provider = '{connector["provider"]}'
          AND name = '{connector["name"]}'
    )
    """


def _insert_knowledge_sql(doc: dict) -> str:
    # Escape single quotes in content
    safe_content = doc["content"].replace("'", "''")
    safe_provenance = doc["provenance"].replace("'", "''")
    return f"""
    INSERT INTO knowledge_documents
        (id, tenant_id, source, external_id, provenance,
         version, status, content, created_at, updated_at)
    SELECT
        '{doc["id"]}',
        '{doc["tenant_id"]}',
        '{doc["source"]}',
        '{doc["external_id"]}',
        '{safe_provenance}',
        1,
        'active',
        '{safe_content}',
        NOW(),
        NOW()
    WHERE NOT EXISTS (
        SELECT 1 FROM knowledge_documents
        WHERE tenant_id = '{doc["tenant_id"]}'
          AND source = '{doc["source"]}'
          AND external_id = '{doc["external_id"]}'
    )
    """


def _insert_skill_sql(skill: dict) -> str:
    import json

    safe_definition = json.dumps(skill["definition"]).replace("'", "''")
    safe_purpose = skill["purpose"].replace("'", "''")
    return f"""
    INSERT INTO skills
        (id, tenant_id, name, version, purpose, status,
         definition, created_at, updated_at)
    SELECT
        '{skill["id"]}',
        '{skill["tenant_id"]}',
        '{skill["name"]}',
        '1',
        '{safe_purpose}',
        'active',
        '{safe_definition}'::jsonb,
        NOW(),
        NOW()
    WHERE NOT EXISTS (
        SELECT 1 FROM skills
        WHERE tenant_id = '{skill["tenant_id"]}'
          AND name = '{skill["name"]}'
          AND version = '1'
    )
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def seed_reference_data(conn: asyncpg.Connection) -> None:
    """Seed the complete reference environment.

    This function is idempotent: calling it multiple times produces no
    duplicates. All INSERT statements use ``WHERE NOT EXISTS`` guards.

    Parameters
    ----------
    conn:
        An active asyncpg connection. The caller is responsible for
        connection lifecycle.
    """
    # 1. Tenants
    for tenant in _TENANTS:
        await conn.execute(_insert_tenant_sql(tenant))

    # 2. Platform administrator (global user, no membership)
    await conn.execute(_insert_user_sql(_PLATFORM_ADMIN))

    # 3. Tenant users and memberships
    for tenant in _TENANTS:
        tenant_slug = tenant["id"].replace("ref-", "")
        for suffix, email_suffix, membership_role, _app_role in _TENANT_USERS:
            user_id = f"ref-{tenant_slug}-{suffix}"
            user = {
                "id": user_id,
                "email": f"{email_suffix}@{tenant_slug}.example.com",
                "username": suffix.replace("-", " ").replace("_", " ").title(),
            }
            await conn.execute(_insert_user_sql(user))

            membership = {
                "id": f"ref-{tenant_slug}-{suffix}",
                "user_id": user_id,
                "tenant_id": tenant["id"],
                "role": membership_role,
            }
            await conn.execute(_insert_membership_sql(membership))

    # 4. Connectors (GitHub + Slack per tenant)
    for tenant in _TENANTS:
        tenant_slug = tenant["id"].replace("ref-", "")
        for conn_def in _CONNECTORS:
            connector = {
                "id": f"ref-{tenant_slug}-{conn_def['provider']}",
                "tenant_id": tenant["id"],
                "provider": conn_def["provider"],
                "name": conn_def["name"],
                "target": conn_def["target"].replace("acme-org", f"{tenant_slug}-org"),
            }
            await conn.execute(_insert_connector_sql(connector))

    # 5. Knowledge documents (2 per tenant)
    for tenant in _TENANTS:
        tenant_slug = tenant["id"].replace("ref-", "")
        for doc_def in _KNOWLEDGE_DOCUMENTS:
            doc = {
                "id": f"ref-{tenant_slug}-{doc_def['external_id_suffix']}",
                "tenant_id": tenant["id"],
                "source": doc_def["source"],
                "external_id": doc_def["external_id_suffix"],
                "provenance": doc_def["provenance"].replace("Acme Technologies", tenant["name"]),
                "content": doc_def["content"].replace("Acme Technologies", tenant["name"]),
            }
            await conn.execute(_insert_knowledge_sql(doc))

    # 6. Skills (1 per tenant)
    for tenant in _TENANTS:
        tenant_slug = tenant["id"].replace("ref-", "")
        for skill_def in _SKILLS:
            skill = {
                "id": f"ref-{tenant_slug}-{skill_def['name'].lower().replace(' ', '-')}",
                "tenant_id": tenant["id"],
                "name": skill_def["name"],
                "purpose": skill_def["purpose"],
                "definition": skill_def["definition"],
            }
            await conn.execute(_insert_skill_sql(skill))


# ---------------------------------------------------------------------------
# Reset helpers (development-only)
# ---------------------------------------------------------------------------

# Deletion order respects FK dependencies.
# Leaf tables first, then parent tables, then root tables.
_RESET_TABLES = [
    # Leaf records (depend on other tables)
    "knowledge_chunks",
    "connector_sync_records",
    "tool_execution_records",
    "skill_execution_records",
    "webhook_events",
    "api_request_records",
    "approval_requests",
    "agent_run_records",
    "llm_usage_records",
    # Parent resources (depend on tenants)
    "knowledge_documents",
    "connector_configs",
    "skills",
    # Join table (depends on users and tenants)
    "memberships",
    # Root entities
    "users",
    "tenants",
    # Orphan table (no code reference)
    "sessions",
]


async def delete_all_application_data(conn: asyncpg.Connection) -> None:
    """Delete all application data while preserving schema.

    This is DEVELOPMENT-ONLY tooling. It deletes all rows from every
    application table in the correct dependency order. The schema,
    constraints, indexes, and database configuration are preserved.

    Parameters
    ----------
    conn:
        An active asyncpg connection.
    """
    for table in _RESET_TABLES:
        await conn.execute(f"DELETE FROM {table}")


async def reset_and_reseed(conn: asyncpg.Connection) -> None:
    """Delete all application data and reseed the reference environment.

    This is DEVELOPMENT-ONLY tooling. It performs a clean reset:
    1. Delete all application data (safe FK order)
    2. Reseed the reference environment

    Parameters
    ----------
    conn:
        An active asyncpg connection.
    """
    await delete_all_application_data(conn)
    await seed_reference_data(conn)
