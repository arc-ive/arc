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

ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(50) DEFAULT 'local';
ALTER TABLE users ADD COLUMN IF NOT EXISTS provider_subject VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_provider_subject
    ON users (auth_provider, provider_subject)
    WHERE provider_subject IS NOT NULL;

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

-- Idempotency key for tool execution deduplication (Issue #136, V2-ADR-019):
-- When set, prevents duplicate handler invocations for the same logical
-- operation. NULL for legacy records and non-idempotent calls.
ALTER TABLE tool_execution_records
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(512);

-- Partial unique index: at most one SUCCESS record per idempotency key.
-- Failed records are NOT constrained — retries after failure must be allowed.
-- Only applies to non-NULL keys (legacy rows have NULL and are unaffected).
CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_execution_records_idempotency_key
    ON tool_execution_records(idempotency_key)
    WHERE idempotency_key IS NOT NULL AND status = 'success';

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

-- Lexical retrieval: PostgreSQL full-text search vector populated on insert
-- via to_tsvector('english', content). GIN index enables fast text matching
-- for the lexical retrieval leg of hybrid RAG (ADR-007).
ALTER TABLE knowledge_chunks
    ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_search_vector
    ON knowledge_chunks USING gin(search_vector);

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

-- Tenant-isolated connector credentials (Issue #137, V2-ADR-015, TRD 20):
-- One encrypted credential per (tenant_id, provider). Credentials are
-- encrypted at rest using AES-256-GCM with a configured key. The
-- key_version supports future key rotation. Plaintext credentials are
-- never stored, logged, or returned through API responses.
CREATE TABLE IF NOT EXISTS connector_credentials (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    encrypted_credential BYTEA NOT NULL,
    key_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    rotated_at TIMESTAMP WITH TIME ZONE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT uq_connector_credentials_tenant_provider UNIQUE (tenant_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_connector_credentials_tenant_id ON connector_credentials(tenant_id);

-- Credential audit events (Issue #137, V2-ADR-015):
-- Metadata-only records of credential lifecycle operations. Never
-- contain plaintext credentials, encryption keys, or decrypted material.
CREATE TABLE IF NOT EXISTS connector_credential_audit (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    operation VARCHAR(50) NOT NULL,
    actor_user_id VARCHAR(255) NOT NULL,
    key_version INTEGER,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_connector_credential_audit_operation
        CHECK (operation IN ('create', 'rotate', 'delete'))
);

CREATE INDEX IF NOT EXISTS idx_connector_credential_audit_tenant_id ON connector_credential_audit(tenant_id);

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

-- Webhook processing lifecycle (Issue #102): extend status to support
-- downstream processing. The original CHECK constraint only allowed
-- 'received'. Processing adds 'processing', 'processed', and 'failed'.
-- These statements are idempotent and safe for both fresh and existing
-- databases. On a fresh database the original constraint is immediately
-- replaced. On an existing database it drops the old constraint and
-- adds the new one.
ALTER TABLE webhook_events
    DROP CONSTRAINT IF EXISTS ck_webhook_events_status;

ALTER TABLE webhook_events
    ADD CONSTRAINT ck_webhook_events_status
    CHECK (status IN ('received', 'processing', 'processed', 'failed'));

-- error_kind: safe hardcoded error category for failed processing.
-- NULL for non-failed events. VARCHAR(100) matches other error_kind
-- columns in the schema.
ALTER TABLE webhook_events
    ADD COLUMN IF NOT EXISTS error_kind VARCHAR(100);

-- processed_at: timestamp when processing completed (success or failure).
-- NULL for unprocessed events.
ALTER TABLE webhook_events
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMP WITH TIME ZONE;

-- Webhook retry/backoff pipeline (Issue #136, V2-ADR-019, TRD 22):
-- retry_count tracks how many retry attempts have been made.
-- next_retry_at is set when status = 'retrying' and cleared on retry.
-- max_retries bounds the total number of retry attempts (default 5).
-- These statements are idempotent and safe for both fresh and existing
-- databases.
ALTER TABLE webhook_events
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE webhook_events
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE webhook_events
    ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 5;

-- Extend the status CHECK constraint to include 'retrying' and
-- 'dead_letter' for bounded retry and dead-letter states.
ALTER TABLE webhook_events
    DROP CONSTRAINT IF EXISTS ck_webhook_events_status;

ALTER TABLE webhook_events
    ADD CONSTRAINT ck_webhook_events_status
    CHECK (status IN ('received', 'processing', 'processed', 'retrying', 'failed', 'dead_letter'));

-- Composite index for webhook retry sweep queries (Issue #136):
-- Supports efficient lookup of retrying events by (tenant, status, schedule)
-- and stuck-processing recovery by (tenant, status, created_at).
CREATE INDEX IF NOT EXISTS idx_webhook_events_retry
    ON webhook_events(tenant_id, status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_webhook_events_stuck
    ON webhook_events(tenant_id, status, created_at);

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
    CONSTRAINT ck_approval_requests_digest CHECK (arguments_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_approval_requests_expiry CHECK (expires_at > created_at)
);

-- Resume support (issue #300). The exact approved arguments, encrypted
-- at rest with the same AES-256-GCM service and key versioning used for
-- connector credentials. Approval is asynchronous by nature: the
-- requester has usually closed the tab by the time a second person
-- decides, so the arguments cannot live in the browser.
--
-- input_summary stays the redacted, truncated, human-readable record and
-- remains the only form ever returned by the API. This column is never
-- serialized into any response. It exists solely so an approved call can
-- be replayed EXACTLY, and it is still validated against
-- arguments_digest before execution, so the stored copy is never trusted
-- on its own.
--
-- Nullable: rows created before this column cannot be resumed
-- server-side, which degrades honestly rather than silently.
ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS encrypted_input BYTEA;
ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS input_key_version INTEGER;

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

-- Expiry ordering invariant (Issue #239): expires_at is strictly after
-- created_at, mirroring the domain model. Follows the DROP IF EXISTS /
-- ADD pair used elsewhere here so existing databases gain the constraint
-- without a migration system (PostgreSQL has no ADD CONSTRAINT IF NOT
-- EXISTS, and a DO block cannot be used because this file is executed by
-- splitting on semicolons).
--
-- The upgrade is deliberately NOT VALID: validating existing rows during
-- startup bootstrap would abort ensure_schema (and therefore the whole
-- application) on any deployment holding a legacy row with
-- expires_at <= created_at. NOT VALID still rejects every new INSERT and
-- every UPDATE that violates the invariant, while pre-existing rows are
-- grandfathered until deliberately remediated (a later VALIDATE
-- CONSTRAINT outside startup is the deferred follow-up). Do NOT add
-- VALIDATE CONSTRAINT here. (No semicolons inside comments: this file is
-- executed by splitting on semicolons.)
ALTER TABLE approval_requests
    DROP CONSTRAINT IF EXISTS ck_approval_requests_expiry;

ALTER TABLE approval_requests
    ADD CONSTRAINT ck_approval_requests_expiry CHECK (expires_at > created_at) NOT VALID;

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
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_agent_run_records_status
        CHECK (status IN ('succeeded', 'failed', 'approval_required', 'max_steps_reached'))
);

CREATE INDEX IF NOT EXISTS idx_agent_run_records_tenant_id
    ON agent_run_records(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_run_records_created_at
    ON agent_run_records(created_at);

-- Skill execution persistence (V2-ADR-014): completes the execution
-- hierarchy (Agent -> Skill -> Tool). One row per
-- SkillExecutionService.execute() call, including controlled failures
-- and approval-required outcomes. agent_run_id links to the owning
-- agent_run_records row when invoked by an Agent (NULL for direct calls).
CREATE TABLE IF NOT EXISTS skill_execution_records (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    skill_id VARCHAR(255) NOT NULL,
    skill_version VARCHAR(50) NOT NULL,
    principal_id VARCHAR(255) NOT NULL,
    agent_run_id VARCHAR(255),
    status VARCHAR(30) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    failure_code VARCHAR(100),
    failure_message TEXT,
    metadata_json JSONB,
    result_summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE,
    CONSTRAINT ck_skill_execution_records_status
        CHECK (status IN ('succeeded', 'failed', 'precondition_failed', 'approval_required', 'denied'))
);

CREATE INDEX IF NOT EXISTS idx_skill_execution_records_tenant_id
    ON skill_execution_records(tenant_id);
CREATE INDEX IF NOT EXISTS idx_skill_execution_records_skill_id
    ON skill_execution_records(skill_id);
CREATE INDEX IF NOT EXISTS idx_skill_execution_records_created_at
    ON skill_execution_records(created_at);
CREATE INDEX IF NOT EXISTS idx_skill_execution_records_agent_run_id
    ON skill_execution_records(agent_run_id)
    WHERE agent_run_id IS NOT NULL;

-- Server-side session storage for Google OIDC authentication.
-- Session IDs are opaque, cryptographically random, and stored in an
-- HttpOnly cookie. The session record maps the session to a user and
-- enforces expiry. No signing secret is needed: the session ID is a
-- random token looked up directly in the database.
CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    csrf_token VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    user_agent TEXT,
    ip_address VARCHAR(45),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Idempotent migration for existing databases: add csrf_token column
-- if it doesn't exist. For fresh databases, the column is already
-- included in the CREATE TABLE statement above.
--
-- The column is added as NULLABLE first so the cleanup DELETE can run
-- without constraint conflicts. All legacy sessions (which lack a
-- valid CSRF token) are removed — users can simply re-authenticate.
-- After cleanup, NOT NULL is enforced.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS csrf_token VARCHAR(255);

-- Remove all legacy sessions without a valid CSRF token.
-- These are unusable because Session.__post_init__ rejects empty tokens.
DELETE FROM sessions WHERE csrf_token IS NULL OR csrf_token = '';

-- Enforce NOT NULL after legacy rows are handled.
-- Safe on fresh databases (all rows already have non-empty csrf_token)
-- and on existing databases (legacy rows deleted above).
ALTER TABLE sessions ALTER COLUMN csrf_token SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);

-- LLM usage telemetry (V2-ADR-024, TRD 13, Issue #141).
-- One row per production LLM API call. Metadata-only: never stores raw
-- prompts, responses, or content. cost_usd is NULL when pricing is
-- unavailable or required token data is missing (never partial).
CREATE TABLE IF NOT EXISTS llm_usage_records (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255),
    request_id VARCHAR(64),
    agent_run_id VARCHAR(255),
    principal_id VARCHAR(255),
    provider VARCHAR(100) NOT NULL,
    model VARCHAR(255) NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    latency_ms INTEGER,
    cost_usd NUMERIC(12,6),
    call_type VARCHAR(50) NOT NULL,
    succeeded BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_llm_usage_records_call_type
        CHECK (call_type IN ('complete', 'propose_tool', 'propose_skill'))
);

ALTER TABLE llm_usage_records ADD COLUMN IF NOT EXISTS succeeded BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_llm_usage_records_tenant_id
    ON llm_usage_records(tenant_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_records_created_at
    ON llm_usage_records(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_records_agent_run_id
    ON llm_usage_records(agent_run_id)
    WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_llm_usage_records_call_type
    ON llm_usage_records(call_type);


-- Platform capability registry (V2-ADR-004, Issue #144):
-- Platform-level enable/disable for each execution domain. Default
-- disabled = hard ceiling by default. One row per known capability.
CREATE TABLE IF NOT EXISTS platform_capabilities (
    capability_id VARCHAR(100) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Tenant capability configuration (V2-ADR-004, Issue #144):
-- Per-tenant enable/disable for each capability. When the platform
-- capability is enabled, the effective state is determined by this
-- row. enabled means the tenant uses the capability, absent or
-- disabled means the tenant does not. A globally enabled capability
-- is NOT automatically enabled for every tenant.
CREATE TABLE IF NOT EXISTS tenant_capabilities (
    tenant_id VARCHAR(255) NOT NULL,
    capability_id VARCHAR(100) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, capability_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tenant_capabilities_tenant_id
    ON tenant_capabilities(tenant_id);

-- Missing foreign key constraint (Issue #188, TRD 26, V2-ADR-028).
--
-- tenant_capabilities.capability_id referenced platform_capabilities with
-- nothing enforcing that the capability exists, so removing a capability left
-- tenant rows pointing at nothing.
--
-- Added at the end of the file because the referenced table must already
-- exist. It follows the DROP IF EXISTS / ADD pair used elsewhere here:
-- PostgreSQL has no ADD CONSTRAINT IF NOT EXISTS, and a DO block cannot be
-- used because this file is executed by splitting on semicolons.
--
-- A tenant's per-capability flag is meaningless once the platform capability
-- it refers to no longer exists, so it goes with it. Note the referenced
-- column is capability_id: platform_capabilities has no id column.
ALTER TABLE tenant_capabilities
    DROP CONSTRAINT IF EXISTS fk_tenant_cap_platform;

ALTER TABLE tenant_capabilities
    ADD CONSTRAINT fk_tenant_cap_platform
    FOREIGN KEY (capability_id) REFERENCES platform_capabilities(capability_id)
    ON DELETE CASCADE;
