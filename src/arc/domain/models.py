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


class RetrievalMethod(str, Enum):
    """Retrieval strategies available to the Secure RAG layer.

    Only ``DENSE_SEMANTIC`` is implemented in this slice. Lexical,
    hybrid/fusion, reranked, and modular routing are later maturity
    layers (proposal §10): they must be added as new enum values behind
    the same security boundary without changing the contract shape.
    """

    DENSE_SEMANTIC = "dense_semantic"


class SkillStatus(str, Enum):
    """Lifecycle status of a Skill.

    Mirrors the ConnectorStatus lifecycle used by the connector foundation.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


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


class ConnectorSyncStatus(str, Enum):
    """Lifecycle status of a connector synchronization attempt."""

    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class ConnectorSyncRecord:
    """Tenant-scoped audit record of one connector synchronization attempt.

    Records contain only safe summaries: item counts and a generic
    ``error_kind``. Provider credentials and raw external payloads are
    never stored here.
    """

    id: str
    tenant_id: str
    connector_id: str
    provider: ConnectorProvider
    status: ConnectorSyncStatus
    items_fetched: int = 0
    error_kind: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Connector sync record ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Tenant ID cannot be empty")
        if not self.connector_id:
            raise ValueError("Connector ID cannot be empty")
        if not isinstance(self.provider, ConnectorProvider):
            raise ValueError(f"Invalid connector provider: {self.provider!r}")
        if not isinstance(self.status, ConnectorSyncStatus):
            raise ValueError(f"Invalid connector sync status: {self.status!r}")
        if not isinstance(self.items_fetched, int) or self.items_fetched < 0:
            raise ValueError("Items fetched must be a non-negative integer")
        if self.status is ConnectorSyncStatus.SUCCESS and self.error_kind:
            raise ValueError("Successful sync records cannot have an error kind")
        if self.status is ConnectorSyncStatus.FAILED and self.items_fetched > 0:
            raise ValueError("Failed sync records cannot report fetched items")


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
    ``sequence`` is the chunk position within the owning document and is
    required for citation in the Approved Context Contract.
    """

    chunk_id: str
    document_id: str
    tenant_id: str
    content: str
    source: KnowledgeSource
    provenance: str
    document_version: int
    sequence: int
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
        if not isinstance(self.sequence, int) or self.sequence < 0:
            raise ValueError("Knowledge match sequence must be a non-negative integer")


@dataclass
class ApprovedContextItem:
    """A single approved context unit for the future Unified Intelligence layer.

    The future LLM/Unified Intelligence layer consumes ONLY these items:
    never raw chunk rows, vectors, or the repository. Each item carries
    already-sanitized content plus the provenance required for citation.

    ``citation_reference`` is a stable, deterministic reference
    (``{document_id}#c{sequence}``) the downstream layer can cite;
    human-readable provenance is carried separately.
    """

    document_id: str
    chunk_id: str
    content: str
    source: KnowledgeSource
    provenance: str
    document_version: int
    sequence: int
    relevance_score: float
    citation_reference: str

    def __post_init__(self):
        if not self.document_id:
            raise ValueError("Approved context item document ID cannot be empty")
        if not self.chunk_id:
            raise ValueError("Approved context item chunk ID cannot be empty")
        if not self.content:
            raise ValueError("Approved context item content cannot be empty")
        if not isinstance(self.source, KnowledgeSource):
            raise ValueError(f"Invalid knowledge source: {self.source!r}")
        if not self.provenance:
            raise ValueError("Approved context item provenance cannot be empty")
        if not isinstance(self.document_version, int) or self.document_version < 1:
            raise ValueError("Approved context item document version must be a positive integer")
        if not isinstance(self.sequence, int) or self.sequence < 0:
            raise ValueError("Approved context item sequence must be a non-negative integer")
        if not isinstance(self.relevance_score, float):
            raise ValueError("Approved context item relevance score must be a float")
        if not self.citation_reference:
            raise ValueError("Approved context item citation reference cannot be empty")


@dataclass(frozen=True)
class ApprovedContextSecurityMetadata:
    """Security assertions recorded on an ApprovedContext.

    This is metadata about the retrieval operation, never an
    authorization mechanism in itself: authorization is enforced by the
    application boundary (trusted TenantContext + permission), and the
    PII Guard runs before content is ever stored or embedded.

    ``authorization_status`` is ``"approved"`` when the caller passed the
    required permission and tenant checks. ``pii_status`` is
    ``"sanitized"`` because only sanitized content is stored and
    embedded; no downstream consumer may assume anything stronger.
    """

    tenant_id: str
    authorization_status: str = "approved"
    pii_status: str = "sanitized"

    def __post_init__(self):
        if not self.tenant_id:
            raise ValueError("Approved context security tenant ID cannot be empty")
        if not self.authorization_status:
            raise ValueError("Approved context authorization status cannot be empty")
        if not self.pii_status:
            raise ValueError("Approved context PII status cannot be empty")


@dataclass
class ApprovedContext:
    """The secure, authorization-validated retrieval contract.

    Produced by ``RetrievalService.approved_search`` from the trusted
    ``TenantContext`` and tenant-scoped retrieval results. A future
    LLM/Unified Intelligence layer receives only this contract — never
    direct access to PostgreSQL, pgvector, raw documents, or
    authorization state.

    ``tenant_id`` is the trusted tenant boundary and ``principal_id`` is
    the authenticated user from the trusted context; both are recorded so
    downstream consumers can attribute and audit the context. Items carry
    sanitized content and provenance only.
    """

    request_id: str
    tenant_id: str
    principal_id: str
    query: str
    retrieval_method: RetrievalMethod
    items: List[ApprovedContextItem] = field(default_factory=list)
    security_metadata: ApprovedContextSecurityMetadata = None

    def __post_init__(self):
        if not self.request_id:
            raise ValueError("Approved context request ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Approved context tenant ID cannot be empty")
        if not self.principal_id:
            raise ValueError("Approved context principal ID cannot be empty")
        if not self.query or not self.query.strip():
            raise ValueError("Approved context query cannot be empty")
        if not isinstance(self.retrieval_method, RetrievalMethod):
            raise ValueError(f"Invalid retrieval method: {self.retrieval_method!r}")
        if not isinstance(self.items, list):
            raise ValueError("Approved context items must be a list")
        if not isinstance(self.security_metadata, ApprovedContextSecurityMetadata):
            raise ValueError("Approved context security metadata is required")
        if self.security_metadata.tenant_id != self.tenant_id:
            raise ValueError(
                "Approved context security metadata tenant must match the context tenant"
            )


@dataclass
class IntelligenceAnswer:
    """The structured result of a Unified Intelligence reasoning step.

    Produced by ``UnifiedIntelligenceService.answer_query`` from the
    trusted ``TenantContext`` and an ``ApprovedContext``. ``answer`` is
    the LLM-generated text or ``None`` when no approved context was
    available (no context means the LLM is never invoked and no answer is
    invented). ``citations`` are the citation references of the approved
    context items that were supplied to the LLM, so every answer is
    attributable. ``context_used`` records whether approved context was
    supplied to the LLM.
    """

    request_id: str
    tenant_id: str
    principal_id: str
    query: str
    answer: Optional[str]
    citations: List[str] = field(default_factory=list)
    retrieval_method: RetrievalMethod = RetrievalMethod.DENSE_SEMANTIC
    context_used: bool = False

    def __post_init__(self):
        if not self.request_id:
            raise ValueError("Intelligence answer request ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Intelligence answer tenant ID cannot be empty")
        if not self.principal_id:
            raise ValueError("Intelligence answer principal ID cannot be empty")
        if not self.query or not self.query.strip():
            raise ValueError("Intelligence answer query cannot be empty")
        if not isinstance(self.answer, str) and self.answer is not None:
            raise ValueError("Intelligence answer must be a string or None")
        if not isinstance(self.citations, list) or not all(
            isinstance(citation, str) for citation in self.citations
        ):
            raise ValueError("Intelligence answer citations must be a list of strings")
        if not isinstance(self.retrieval_method, RetrievalMethod):
            raise ValueError(f"Invalid retrieval method: {self.retrieval_method!r}")
        if not isinstance(self.context_used, bool):
            raise ValueError("Intelligence answer context_used must be a boolean")
        if self.context_used and not self.answer:
            raise ValueError("An answer is required when context was used")


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
