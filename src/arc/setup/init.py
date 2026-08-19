"""Database setup utilities for Arc multi-tenant foundation."""

import os
import subprocess
import sys


def run_command(command: list[str], description: str) -> None:
    """Run a command and check its success."""
    print(f"\n{description}")
    print(f"Running: {' '.join(command)}")

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    if result.returncode != 0:
        print(f"STDOUT:\n{result.stdout}")
        print(f"STDERR:\n{result.stderr}")
        raise RuntimeError(f"Command failed: {' '.join(command)}")

    print("Success!")


def setup_database(database_url: str) -> None:
    """Set up the Arc database with required tables."""
    # Parse database URL.
    # Format:
    # postgresql://user:password@localhost:5432/database
    parts = database_url.replace("postgresql://", "").split("@")
    auth = parts[0].split(":")
    host_db = parts[1].split("/")

    user = auth[0]
    password = auth[1]
    host_port = host_db[0]
    database = host_db[1]

    host = host_port.split(":")[0]
    port = host_port.split(":")[1]

    # Set password environment for PostgreSQL commands.
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    try:
        # Try to connect to the existing database.
        run_command(
            [
                "psql",
                "-h",
                host,
                "-p",
                port,
                "-U",
                user,
                "-d",
                database,
                "-c",
                "SELECT 1",
            ],
            "Testing database connection",
        )

        print(f"Database '{database}' already exists and is accessible.")

    except RuntimeError:
        # Database doesn't exist, create it.
        print(f"Database '{database}' does not exist. Creating...")

        run_command(
            [
                "createdb",
                "-h",
                host,
                "-p",
                port,
                "-U",
                user,
                database,
            ],
            "Creating database",
        )

    # Run schema initialization.
    psql_cmd = [
        "psql",
        "-h",
        host,
        "-p",
        port,
        "-U",
        user,
        "-d",
        database,
    ]

    init_script = """
    -- Arc Multi-Tenant Database Schema
    -- Created by Arc Platform Security Foundation setup

    CREATE TABLE IF NOT EXISTS tenants (
        id VARCHAR(255) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'active',
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS users (
        id VARCHAR(255) PRIMARY KEY,
        email VARCHAR(255) NOT NULL,
        username VARCHAR(255),
        status VARCHAR(50) NOT NULL DEFAULT 'active',
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(email)
    );

    CREATE TABLE IF NOT EXISTS memberships (
        id VARCHAR(255) PRIMARY KEY,
        user_id VARCHAR(255) NOT NULL,
        tenant_id VARCHAR(255) NOT NULL,
        role VARCHAR(50) NOT NULL DEFAULT 'member',
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, tenant_id),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_memberships_user_id
        ON memberships(user_id);

    CREATE INDEX IF NOT EXISTS idx_memberships_tenant_id
        ON memberships(tenant_id);

    CREATE INDEX IF NOT EXISTS idx_users_email
        ON users(email);

    -- Insert a demo tenant if none exists.
    INSERT INTO tenants (id, name, status)
    SELECT 'demo-tenant', 'Demo Tenant', 'active'
    WHERE NOT EXISTS (
        SELECT 1 FROM tenants
    );

    -- Insert a demo user if none exists.
    INSERT INTO users (id, email, username, status)
    SELECT 'demo-user', 'demo@example.com', 'demo_user', 'active'
    WHERE NOT EXISTS (
        SELECT 1 FROM users
    );

    -- Create demo membership if it doesn't exist.
    INSERT INTO memberships (id, user_id, tenant_id, role)
    SELECT 'demo-membership', 'demo-user', 'demo-tenant', 'owner'
    WHERE NOT EXISTS (
        SELECT 1
        FROM memberships
        WHERE user_id = 'demo-user'
          AND tenant_id = 'demo-tenant'
    );
    """

    run_command(
        psql_cmd + ["-c", init_script.strip()],
        "Initializing database schema",
    )


if __name__ == "__main__":
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://arc:arc-dev-password@localhost:5432/arc",
    )

    print("Arc Platform Security Foundation - Database Setup")
    print("=" * 60)

    try:
        setup_database(database_url)
        print("\n✓ Database setup completed successfully!")
        print("\nDemo data created:")
        print("- Tenant: demo-tenant (Demo Tenant)")
        print("- User: demo-user (demo@example.com)")
        print("- Membership: demo-user -> demo-tenant (owner)")
    except Exception as e:
        print(f"\n✗ Database setup failed: {e}")
        sys.exit(1)
