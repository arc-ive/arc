"""Database setup utilities for Arc multi-tenant foundation.

``src/arc/db/schema.sql`` is the single source of truth for the
database schema (Issue #207, V2-ADR-028). This module contains no
inline DDL; it provisions the schema by executing that file.

Usage:
    python -m arc.setup.init
"""

import os
import subprocess
import sys
from pathlib import Path


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
    """Set up the Arc database with required tables.

    Ensures the database exists (creating it if needed) and then
    applies ``src/arc/db/schema.sql`` — the single authoritative
    schema — via ``psql -f``. All statements in that file are
    idempotent (``IF NOT EXISTS``), so this is safe to run
    repeatedly.
    """
    parts = database_url.replace("postgresql://", "").split("@")
    auth = parts[0].split(":")
    host_db = parts[1].split("/")

    user = auth[0]
    password = auth[1]
    host_port = host_db[0]
    database = host_db[1]

    host = host_port.split(":")[0]
    port = host_port.split(":")[1]

    env = os.environ.copy()
    env["PGPASSWORD"] = password

    try:
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

    schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    if not schema_path.exists():
        raise RuntimeError(f"Schema file not found: {schema_path}")

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
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        str(schema_path),
    ]

    run_command(
        psql_cmd,
        f"Applying database schema from {schema_path.name}",
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
        print("\nSchema initialized. Reference data will be seeded on application startup.")
    except Exception as e:
        print(f"\n✗ Database setup failed: {e}")
        sys.exit(1)
