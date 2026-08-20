"""Domain models for multi-tenancy foundation."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class UserRole(str, Enum):
    """Initial role for membership."""

    OWNER = "owner"
    MEMBER = "member"
    VIEWER = "viewer"


class ConnectorProvider(str, Enum):
    """Supported connector providers."""

    SLACK = "slack"
    GITHUB = "github"
    GOOGLE_DRIVE = "google_drive"
    LINEAR = "linear"


class ConnectorStatus(str, Enum):
    """Lifecycle status of a connector configuration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class KnowledgeStatus(str, Enum):
    """Lifecycle status of a knowledge document."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class KnowledgeSource(str, Enum):
    """Origin of a knowledge document.

    Source values map to the semantic knowledge categories in TRD 9.2
    (company policies, support procedures, incident reports,
    troubleshooting documents, internal knowledge, historical solutions).
    """

    POLICY = "policy"
    PROCEDURE = "procedure"
    INCIDENT_REPORT = "incident_report"
    TROUBLESHOOTING = "troubleshooting"
    INTERNAL_KNOWLEDGE = "internal_knowledge"
    SOLUTION = "solution"


class SkillStatus(str, Enum):
    """Lifecycle status of a Skill.

    Mirrors the ConnectorStatus lifecycle used by the connector foundation.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class ToolRiskLevel(str, Enum):
    """Risk classification of a platform-approved AI Tool (PRD 15).

    High-risk tool execution requires human approval before the tool is
    executed (TRD 17.3); the human-approval gate is part of the Human
    Intervention capability and is not implemented here.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolExecutionStatus(str, Enum):
    """Final status of a controlled tool execution attempt (TRD 14.2).

    Every controlled execution attempt produces an observable record;
    a record therefore has exactly one terminal status. The outcome is
    represented safely: details live in ``error_kind`` only for failures
    and never contain secrets, stack traces, or sensitive payloads.
    """

    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class Tenant:
    """Tenant domain model."""

    id: str
    name: str
    status: str = "active"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Tenant ID cannot be empty")
        if not self.name:
            raise ValueError("Tenant name cannot be empty")


@dataclass
class User:
    """User domain model."""

    id: str
    email: str
    username: Optional[str] = None
    status: str = "active"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("User ID cannot be empty")
        if not self.email:
            raise ValueError("User email cannot be empty")


@dataclass
class Membership:
    """User-Tenant relationship domain model."""

    id: str
    user_id: str
    tenant_id: str
    role: UserRole = UserRole.MEMBER
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Membership ID cannot be empty")
        if not self.user_id:
            raise ValueError("User ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Tenant ID cannot be empty")

    def is_owner(self) -> bool:
        """Check if membership is an owner role."""
        return self.role == UserRole.OWNER


@dataclass
class TenantContext:
    """Application-level tenant context."""

    tenant_id: str
    tenant_name: str
    user_id: str
    role: UserRole
    # This context must not trust arbitrary tenant IDs from clients
    # It must be established from authenticated principals

    def __post_init__(self):
        if not self.tenant_id:
            raise ValueError("Tenant ID cannot be empty in context")
        if not self.tenant_name:
            raise ValueError("Tenant name cannot be empty in context")
        if not self.user_id:
            raise ValueError("User ID cannot be empty in context")

    @property
    def is_valid(self) -> bool:
        """Validate the tenant context."""
        return bool(self.tenant_id and self.user_id and self.role)


@dataclass
class ConnectorConfig:
    """Tenant-owned connector configuration."""

    id: str
    tenant_id: str
    provider: ConnectorProvider
    name: str
    status: ConnectorStatus = ConnectorStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Connector config ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Tenant ID cannot be empty")
        if not self.name:
            raise ValueError("Connector config name cannot be empty")
        if not isinstance(self.provider, ConnectorProvider):
            raise ValueError(f"Invalid connector provider: {self.provider!r}")
        if not isinstance(self.status, ConnectorStatus):
            raise ValueError(f"Invalid connector status: {self.status!r}")


@dataclass
class KnowledgeDocument:
    """Tenant-owned knowledge document stored in the Company Brain.

    ``content`` holds the PII-sanitized text. Raw content must never be
    persisted: the ingestion boundary (KnowledgeService + PiiGuardService)
    sanitizes content before this model reaches persistence.

    ``version`` is stored document metadata (TRD 9.1). This foundation
    slice does not implement document revision/update semantics, and no
    logical document identity or uniqueness relationship between documents
    and versions is claimed; future document lifecycle work may define
    that model.
    """

    id: str
    tenant_id: str
    source: KnowledgeSource
    provenance: str
    content: str
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE
    version: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Knowledge document ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Tenant ID cannot be empty")
        if not isinstance(self.source, KnowledgeSource):
            raise ValueError(f"Invalid knowledge source: {self.source!r}")
        if not self.provenance:
            raise ValueError("Knowledge document provenance cannot be empty")
        if not isinstance(self.status, KnowledgeStatus):
            raise ValueError(f"Invalid knowledge status: {self.status!r}")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("Knowledge document version must be a positive integer")
        if not self.content:
            raise ValueError("Knowledge document content cannot be empty")


@dataclass
class KnowledgeChunk:
    """A deterministic segment of a sanitized knowledge document.

    Chunks are derived exclusively from already-sanitized knowledge
    content (Secure RAG foundation). The ``embedding`` vector is a
    storage/retrieval concern and is never part of this domain model: the
    repository receives embedding vectors alongside chunks.

    ``tenant_id`` and ``document_id`` preserve the ownership required for
    tenant isolation at the SQL boundary.
    """

    id: str
    document_id: str
    tenant_id: str
    content: str
    sequence: int
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Knowledge chunk ID cannot be empty")
        if not self.document_id:
            raise ValueError("Knowledge chunk document ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Tenant ID cannot be empty")
        if not self.content:
            raise ValueError("Knowledge chunk content cannot be empty")
        if not isinstance(self.sequence, int) or self.sequence < 0:
            raise ValueError("Knowledge chunk sequence must be a non-negative integer")


@dataclass
class KnowledgeMatch:
    """A retrieved knowledge chunk with its owning document context.

    Secure RAG retrieval returns chunks with their document provenance so
    results are explainable. ``content`` is always already-sanitized
    content: raw content never reaches persistence or retrieval.
    """

    chunk_id: str
    document_id: str
    tenant_id: str
    content: str
    source: KnowledgeSource
    provenance: str
    document_version: int
    similarity: float

    def __post_init__(self):
        if not self.chunk_id:
            raise ValueError("Knowledge match chunk ID cannot be empty")
        if not self.document_id:
            raise ValueError("Knowledge match document ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Tenant ID cannot be empty")
        if not isinstance(self.source, KnowledgeSource):
            raise ValueError(f"Invalid knowledge source: {self.source!r}")


@dataclass
class Skill:
    """Tenant-owned Skill domain model.

    A Skill converts a company procedure into a structured, reusable
    workflow that Unified Intelligence can apply (PRD 13, TRD 13.1). The
    typed fields are the application-level contract; persistence may split
    the body into a JSONB ``definition`` column without changing this
    model. The exact Skill serialization format remains open
    (ADR-001, TRD 37).
    """

    id: str
    tenant_id: str
    name: str
    purpose: str
    version: str = "1"
    inputs: List[str] = field(default_factory=list)
    preconditions: List[str] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    approval_required: bool = False
    expected_output: Optional[str] = None
    failure_behavior: Optional[str] = None
    provenance: Optional[str] = None
    status: SkillStatus = SkillStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Skill ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Tenant ID cannot be empty")
        if not self.name:
            raise ValueError("Skill name cannot be empty")
        if not self.purpose:
            raise ValueError("Skill purpose cannot be empty")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("Skill version must be a non-empty string")
        if not isinstance(self.status, SkillStatus):
            raise ValueError(f"Invalid skill status: {self.status!r}")
        if not isinstance(self.approval_required, bool):
            raise ValueError("approval_required must be a boolean")
        for list_field_name, list_value in (
            ("inputs", self.inputs),
            ("preconditions", self.preconditions),
            ("steps", self.steps),
            ("constraints", self.constraints),
            ("allowed_tools", self.allowed_tools),
        ):
            if not isinstance(list_value, list) or not all(
                isinstance(item, str) for item in list_value
            ):
                raise ValueError(f"{list_field_name} must be a list of strings")


@dataclass
class ToolExecutionRecord:
    """Tenant-scoped audit record for one controlled AI Tool invocation.

    Produced for every controlled execution attempt (TRD 14.1/14.2),
    including controlled failures. Records contain only safe, sanitized
    summaries: never secrets, credentials, raw sensitive payloads, or
    internal stack traces. The tenant boundary comes exclusively from the
    trusted ``TenantContext`` established by X-10; the repository enforces
    it in SQL.
    """

    id: str
    tenant_id: str
    tool_name: str
    tool_version: str
    status: ToolExecutionStatus
    risk_level: ToolRiskLevel
    input_summary: str
    output_summary: Optional[str] = None
    error_kind: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Tool execution record ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Tenant ID cannot be empty")
        if not self.tool_name:
            raise ValueError("Tool name cannot be empty")
        if not self.tool_version:
            raise ValueError("Tool version cannot be empty")
        if not isinstance(self.status, ToolExecutionStatus):
            raise ValueError(f"Invalid tool execution status: {self.status!r}")
        if not isinstance(self.risk_level, ToolRiskLevel):
            raise ValueError(f"Invalid tool risk level: {self.risk_level!r}")
        if not isinstance(self.input_summary, str) or not self.input_summary:
            raise ValueError("Tool input summary must be a non-empty string")
