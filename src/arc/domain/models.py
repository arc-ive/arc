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


class ToolAuthorizationOutcome(str, Enum):
    """Authorization decision for a controlled tool execution attempt.

    Records the fail-closed per-tool authorization outcome (TRD 14.2):
    ``GRANTED`` means the caller held ``tool:execute`` and every
    permission required by the tool; ``DENIED`` means the attempt was
    refused before any handler could run (unknown tool, missing/invalid
    permission metadata, or insufficient permissions).
    """

    GRANTED = "granted"
    DENIED = "denied"


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

    ``version`` is structured document metadata (TRD 9.1): it starts at 1
    and increments by exactly one for every accepted content change of the
    same logical document. No historical revision rows are kept.

    Logical identity is defined by ADR-003 as ``(tenant_id, source,
    external_id)``. ``external_id`` is the ingestion writer's stable
    identifier for one logical document (for example connector
    synchronization binds ``"{provider}:{source_id}"``). It is optional:
    documents ingested without an external identity are unique per
    ingestion and keep pre-ADR create-always behavior.
    """

    id: str
    tenant_id: str
    source: KnowledgeSource
    provenance: str
    content: str
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE
    version: int = 1
    external_id: Optional[str] = None
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
        if self.external_id is not None:
            if not isinstance(self.external_id, str) or not self.external_id:
                raise ValueError(
                    "Knowledge document external_id must be a non-empty string when provided"
                )
            if len(self.external_id) > 255:
                raise ValueError("Knowledge document external_id cannot exceed 255 characters")


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


@dataclass
class ToolExecutionRecord:
    """Tenant-scoped audit record for one controlled AI Tool invocation.

    Produced for every controlled execution attempt (TRD 14.1/14.2),
    including controlled failures. The audit contract is explicit:

    - who requested the invocation (``user_id``, the trusted JWT subject);
    - which tenant the attempt was scoped to (``tenant_id``);
    - which platform-approved tool and version (``tool_name``,
      ``tool_version``);
    - the authorization decision (``authorization_outcome``);
    - the policy/risk outcome (``risk_level``, plus ``error_kind`` when a
      policy or execution refusal occurred);
    - the terminal execution status and the execution identifier (``id``)
      with the record timestamp (``created_at``).

    Records contain only safe, sanitized summaries: never secrets,
    credentials, raw sensitive payloads, or internal stack traces. The
    tenant boundary comes exclusively from the trusted ``TenantContext``
    established by X-10; the repository enforces it in SQL.
    """

    id: str
    tenant_id: str
    user_id: str
    tool_name: str
    tool_version: str
    status: ToolExecutionStatus
    risk_level: ToolRiskLevel
    input_summary: str
    authorization_outcome: ToolAuthorizationOutcome = ToolAuthorizationOutcome.GRANTED
    output_summary: Optional[str] = None
    error_kind: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Tool execution record ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Tenant ID cannot be empty")
        if not self.user_id:
            raise ValueError("User ID cannot be empty")
        if not self.tool_name:
            raise ValueError("Tool name cannot be empty")
        if not self.tool_version:
            raise ValueError("Tool version cannot be empty")
        if not isinstance(self.status, ToolExecutionStatus):
            raise ValueError(f"Invalid tool execution status: {self.status!r}")
        if not isinstance(self.authorization_outcome, ToolAuthorizationOutcome):
            raise ValueError(f"Invalid tool authorization outcome: {self.authorization_outcome!r}")
        if not isinstance(self.risk_level, ToolRiskLevel):
            raise ValueError(f"Invalid tool risk level: {self.risk_level!r}")
        if not isinstance(self.input_summary, str) or not self.input_summary:
            raise ValueError("Tool input summary must be a non-empty string")


class WebhookEventStatus(str, Enum):
    """Lifecycle status of an ingested webhook event.

    The Webhooks foundation slice establishes a single terminal state:
    every accepted event is validated and recorded as ``received``
    (PRD 16 processing status). Triggering downstream processing is a
    future slice; new states are added only through approved decisions.
    """

    RECEIVED = "received"


@dataclass
class WebhookEvent:
    """Tenant-scoped record of one ingested webhook event (PRD 23 "Event").

    The record is deliberately metadata-only: it never stores the raw
    external payload. Webhook payloads are untrusted external input
    (ADR-001 webhook security boundary) and may contain PII; until an
    approved PII/storage decision exists for event content, only safe
    envelope metadata is persisted:

    - which ingestion endpoint received the event (``endpoint_id``);
    - the tenant the event is bound to (``tenant_id``, resolved from the
      trusted endpoint configuration, NEVER from request input);
    - the sender-supplied unique event identifier (``event_id``), used
      for duplicate handling;
    - the event type label and payload size in bytes;
    - the processing status and record timestamp.
    """

    id: str
    tenant_id: str
    endpoint_id: str
    event_id: str
    event_type: str
    status: WebhookEventStatus = WebhookEventStatus.RECEIVED
    payload_size_bytes: int = 0
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Webhook event ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Webhook event tenant ID cannot be empty")
        if not self.endpoint_id:
            raise ValueError("Webhook event endpoint ID cannot be empty")
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError("Webhook event identifier cannot be empty")
        if len(self.event_id) > 255:
            raise ValueError("Webhook event identifier cannot exceed 255 characters")
        if not isinstance(self.event_type, str) or not self.event_type:
            raise ValueError("Webhook event type cannot be empty")
        if len(self.event_type) > 100:
            raise ValueError("Webhook event type cannot exceed 100 characters")
        if not isinstance(self.status, WebhookEventStatus):
            raise ValueError(f"Invalid webhook event status: {self.status!r}")
        if not isinstance(self.payload_size_bytes, int) or isinstance(
            self.payload_size_bytes, bool
        ):
            raise ValueError("Webhook event payload size must be an integer")
        if self.payload_size_bytes < 0:
            raise ValueError("Webhook event payload size cannot be negative")
