CREATE TABLE IF NOT EXISTS tenants (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    industry VARCHAR(255),
    address VARCHAR(500),
    phone VARCHAR(100),
    website VARCHAR(2048),
    logo_url VARCHAR(2048),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS industry VARCHAR(255);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS address VARCHAR(500);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS phone VARCHAR(100);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS website VARCHAR(2048);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_url VARCHAR(2048);

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

CREATE INDEX IF NOT EXISTS idx_memberships_user_id ON memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_tenant_id ON memberships(tenant_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS connector_configs (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    target VARCHAR(500) NOT NULL DEFAULT '',
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    UNIQUE(tenant_id, provider, name)
);

CREATE INDEX IF NOT EXISTS idx_connector_configs_tenant_id ON connector_configs(tenant_id);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    source VARCHAR(50) NOT NULL,
    provenance VARCHAR(255) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_knowledge_documents_version CHECK (version >= 1),
    CONSTRAINT ck_knowledge_documents_status CHECK (status IN ('active', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_knowledge_documents_tenant_id ON knowledge_documents(tenant_id);

-- Company Brain document identity (ADR-003): logical identity is the
-- triple (tenant_id, source, external_id). NULL identities are excluded
-- from the index and keep create-always behavior. Both statements are
-- idempotent under bootstrap and safe against pre-existing rows where
-- external_id is all NULL. NOTE: comment text must never contain a
-- semicolon because the test/bootstrap splits this file on semicolons.
ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS external_id VARCHAR(255);
CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_documents_identity
    ON knowledge_documents (tenant_id, source, external_id)
    WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS skills (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL DEFAULT '1',
    purpose TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    definition JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    UNIQUE(tenant_id, name, version)
);

CREATE INDEX IF NOT EXISTS idx_skills_tenant_id ON skills(tenant_id);

CREATE TABLE IF NOT EXISTS tool_execution_records (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    tool_name VARCHAR(255) NOT NULL,
    tool_version VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    authorization_outcome VARCHAR(50) NOT NULL,
    risk_level VARCHAR(50) NOT NULL,
    input_summary TEXT NOT NULL,
    output_summary TEXT,
    error_kind VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_tool_execution_records_status CHECK (status IN ('success', 'failed')),
    CONSTRAINT ck_tool_execution_records_authorization_outcome
        CHECK (authorization_outcome IN ('granted', 'denied')),
    CONSTRAINT ck_tool_execution_records_risk_level CHECK (risk_level IN ('low', 'medium', 'high'))
);

-- Idempotent audit-contract columns: schema bootstrap also runs against
-- databases created before the audit contract was extended. Historical
-- records predate that contract: their user identity and authorization
-- decision were never recorded, so the migrated columns are NULLABLE and
-- the migration NEVER fabricates a user identity or a GRANTED
-- authorization for them. New records always carry a real trusted
-- user_id and a real authorization outcome (GRANTED or DENIED), enforced
-- by ToolExecutionService (fresh installs additionally keep NOT NULL
-- columns at table creation)
ALTER TABLE tool_execution_records ADD COLUMN IF NOT EXISTS user_id VARCHAR(255);
ALTER TABLE tool_execution_records ADD COLUMN IF NOT EXISTS authorization_outcome VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_tool_execution_records_tenant_id ON tool_execution_records(tenant_id);

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id VARCHAR(255) PRIMARY KEY,
    document_id VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_knowledge_chunks_sequence CHECK (sequence >= 0)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_tenant_id ON knowledge_chunks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id ON knowledge_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS connector_sync_records (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    connector_id VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    items_fetched INTEGER NOT NULL DEFAULT 0,
    error_kind VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (connector_id) REFERENCES connector_configs(id) ON DELETE CASCADE,
    CONSTRAINT ck_connector_sync_records_status CHECK (status IN ('success', 'failed')),
    CONSTRAINT ck_connector_sync_records_items_fetched CHECK (items_fetched >= 0)
);

CREATE INDEX IF NOT EXISTS idx_connector_sync_records_tenant_id ON connector_sync_records(tenant_id);

-- Webhooks foundation (PRD 16, TRD 16): tenant-scoped records of
-- validated inbound webhook events. Records are metadata-only by design:
-- raw external payloads are untrusted input (ADR-001 webhook security
-- boundary) and are never persisted. The (tenant_id, event_id)
-- uniqueness pair is the duplicate-handling contract: a re-delivered
-- event resolves to the original record instead of creating a new row.
CREATE TABLE IF NOT EXISTS webhook_events (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    endpoint_id VARCHAR(255) NOT NULL,
    event_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'received',
    payload_size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_webhook_events_status CHECK (status IN ('received')),
    CONSTRAINT ck_webhook_events_payload_size CHECK (payload_size_bytes >= 0),
    CONSTRAINT uq_webhook_events_tenant_event UNIQUE (tenant_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_tenant_id ON webhook_events(tenant_id);
-- Observability foundation (PRD 17, TRD 17/28/31): metadata-only HTTP
-- telemetry owned by the Observability/API layer. This is NOT a generic
-- event table and never duplicates subsystem records - tool executions,
-- connector syncs, and webhook events remain in their authoritative
-- tables and are aggregated there at read time.
-- tenant_id is NULL for public/unauthenticated or unattributable requests:
-- attribution uses SUCCESS-GATED PATH-PARAM labeling only (status < 400 on
-- an authenticated tenant route) and NEVER establishes identity or
-- authorization. route_template stores the normalized route template,
-- never raw paths or query strings. No bodies, prompts, answers, tokens,
-- secrets, or PII are ever persisted here (TRD 20/28).
CREATE TABLE IF NOT EXISTS api_request_records (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255),
    request_id VARCHAR(64) NOT NULL,
    method VARCHAR(10) NOT NULL,
    route_template VARCHAR(255) NOT NULL,
    status_code INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    error_kind VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_api_request_records_status_code CHECK (status_code BETWEEN 100 AND 599),
    CONSTRAINT ck_api_request_records_duration CHECK (duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_api_request_records_tenant_id ON api_request_records(tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_request_records_created_at ON api_request_records(created_at);

-- Human Intervention approval gate (V1 foundation - ADR-004 extension
-- point). One row per required approval, bound to the EXACT validated
-- request via arguments_digest (SHA-256 of the canonical JSON of the
-- pydantic-VALIDATED tool input). Raw tool arguments are never stored.
-- Lifecycle: pending -> approved | rejected | expired (terminal) and
-- approved -> consumed exactly once. EXPIRED is applied lazily at
-- decision/consumption time - reads derive it from expires_at. Tenant
-- binding comes exclusively from the trusted execution context and every
-- query is tenant-scoped at the SQL level.
CREATE TABLE IF NOT EXISTS approval_requests (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    requester_user_id VARCHAR(255) NOT NULL,
    tool_name VARCHAR(255) NOT NULL,
    tool_version VARCHAR(50) NOT NULL,
    risk_level VARCHAR(50) NOT NULL,
    input_summary TEXT NOT NULL,
    arguments_digest CHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    decided_at TIMESTAMP WITH TIME ZONE,
    decided_by_user_id VARCHAR(255),
    consumed_at TIMESTAMP WITH TIME ZONE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_approval_requests_status
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'consumed')),
    CONSTRAINT ck_approval_requests_digest CHECK (arguments_digest ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_tenant_status
    ON approval_requests(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_approval_requests_created_at
    ON approval_requests(created_at);

-- Race-safe idempotent creation: at most one OPEN (pending) approval per
-- logical binding (tenant, tool, version, digest). Partial index covers
-- only pending rows so decided/expired/consumed rows do not collide.
CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_requests_open_binding
    ON approval_requests(tenant_id, tool_name, tool_version, arguments_digest)
    WHERE status = 'pending';

-- Agent execution trace (PRD 17 O-6): persisted run-level records.
-- Observability is an aggregation/read layer (not a second source of
-- truth) and this table IS the authoritative write path for agent runs
-- because no prior table persisted them.
CREATE TABLE IF NOT EXISTS agent_run_records (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    principal_id VARCHAR(255) NOT NULL,
    goal TEXT NOT NULL,
    status VARCHAR(30) NOT NULL,
    error_kind VARCHAR(100),
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_agent_run_records_status
        CHECK (status IN ('succeeded', 'failed', 'approval_required', 'max_steps_reached'))
);

CREATE INDEX IF NOT EXISTS idx_agent_run_records_tenant_id
    ON agent_run_records(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_run_records_created_at
    ON agent_run_records(created_at);
