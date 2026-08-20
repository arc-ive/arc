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

CREATE INDEX IF NOT EXISTS idx_memberships_user_id ON memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_tenant_id ON memberships(tenant_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS connector_configs (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
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
    embedding vector(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_knowledge_chunks_sequence CHECK (sequence >= 0)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_tenant_id ON knowledge_chunks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id ON knowledge_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
