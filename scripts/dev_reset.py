#!/usr/bin/env python3
"""Development-only database reset and reseed tool.

This script performs a clean reset of the Arc development database:
1. Deletes all application data (safe FK order)
2. Reseds the production-like reference environment

IMPORTANT: This is DEVELOPMENT-ONLY tooling.
- It must never be exposed through an API.
- It must require explicit manual invocation.
- It preserves the database schema, constraints, indexes, and extensions.
- It does NOT drop/recreate the database or schema.

Usage:
    python -m scripts.dev_reset
    python scripts/dev_reset.py

The DATABASE_URL environment variable is used for connection.
Defaults to: postgresql://arc:arc-dev-password@localhost:5432/arc
"""

import asyncio
import os
import sys

# Add the project root to the path so we can import arc modules.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import asyncpg  # noqa: E402


async def main() -> None:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://arc:arc-dev-password@localhost:5432/arc",
    )

    print("Arc Development Reset")
    print("=" * 60)
    db_display = database_url.split("@")[-1] if "@" in database_url else database_url
    print(f"Database: {db_display}")
    print()

    # Connect to the database.
    conn = await asyncpg.connect(database_url)

    try:
        # Show current state.
        tenant_count = await conn.fetchval("SELECT count(*) FROM tenants")
        user_count = await conn.fetchval("SELECT count(*) FROM users")
        membership_count = await conn.fetchval("SELECT count(*) FROM memberships")
        print(
            f"Current state: {tenant_count} tenants, "
            f"{user_count} users, {membership_count} memberships"
        )
        print()

        # Perform reset and reseed.
        from arc.setup.reference_data import reset_and_reseed

        print("Deleting all application data...")
        await reset_and_reseed(conn)

        # Show result.
        tenant_count = await conn.fetchval("SELECT count(*) FROM tenants")
        user_count = await conn.fetchval("SELECT count(*) FROM users")
        membership_count = await conn.fetchval("SELECT count(*) FROM memberships")
        connector_count = await conn.fetchval(
            "SELECT count(*) FROM connector_configs"
        )
        knowledge_count = await conn.fetchval(
            "SELECT count(*) FROM knowledge_documents"
        )
        skill_count = await conn.fetchval("SELECT count(*) FROM skills")

        print()
        print("Reset complete! Reference environment:")
        print(f"  Tenants:            {tenant_count}")
        print(f"  Users:              {user_count}")
        print(f"  Memberships:        {membership_count}")
        print(f"  Connector configs:  {connector_count}")
        print(f"  Knowledge docs:     {knowledge_count}")
        print(f"  Skills:             {skill_count}")
        print()
        print("Application role assignments must be configured via")
        print("the APPLICATION_ROLE_ASSIGNMENTS environment variable.")
        print("See .env.example for the required format.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
