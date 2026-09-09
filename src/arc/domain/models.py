"""Domain models for multi-tenancy foundation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


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
    layers (proposal ┬º10): they must be added as new enum values behind
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
    industry: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
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
    auth_provider: str = "local"
    provider_subject: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("User ID cannot be empty")
        if not self.email:
            raise ValueError("User email cannot be empty")


@dataclass
class Session:
    """Server-side session for authenticated users."""

    id: str
    user_id: str
    csrf_token: str
    created_at: datetime
    expires_at: datetime
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None

    def __post_init__(self):
        if not self.id:
            raise ValueError("Session ID cannot be empty")
        if not self.user_id:
            raise ValueError("Session user_id cannot be empty")
        if not self.csrf_token:
            raise ValueError("Session csrf_token cannot be empty")

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


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
    target: str = ""
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
    LLM/Unified Intelligence layer receives only this contract ΓÇö never
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


@dataclass(frozen=True)
class ToolProposal:
    """One LLM-proposed tool action (ADR-004).

    A proposal is UNTRUSTED model output: a request that the application
    may validate, authorize, and execute — never a grant. Use
    :meth:`parse` to strictly validate raw model output; anything that is
    not exactly this shape parses to ``None`` and the intelligence path
    continues without a tool (fail closed, no exception escapes).
    """

    tool_name: str
    arguments: Dict[str, Any]

    MAX_TOOL_NAME_LENGTH = 255

    @classmethod
    def parse(cls, raw: Any) -> Optional["ToolProposal"]:
        """Strictly parse untrusted raw model output into a proposal.

        Returns ``None`` (never raises) when ``raw`` is not exactly a
        mapping with exactly the keys ``tool_name`` (non-empty string of
        at most 255 characters) and ``arguments`` (a mapping). Unknown or
        missing fields are rejected; values are NOT coerced.
        """
        if not isinstance(raw, dict):
            return None
        if set(raw.keys()) != {"tool_name", "arguments"}:
            return None
        tool_name = raw["tool_name"]
        arguments = raw["arguments"]
        if not isinstance(tool_name, str) or not tool_name.strip():
            return None
        if len(tool_name) > cls.MAX_TOOL_NAME_LENGTH:
            return None
        if not isinstance(arguments, dict):
            return None
        if not all(isinstance(key, str) for key in arguments):
            return None
        return cls(tool_name=tool_name, arguments=dict(arguments))


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
    tool_executions: List[Dict[str, str]] = field(default_factory=list)

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
        if not isinstance(self.tool_executions, list) or len(self.tool_executions) > 1:
            raise ValueError("Intelligence answer supports at most one tool execution in V1")
        for entry in self.tool_executions:
            if not isinstance(entry, dict) or set(entry.keys()) != {
                "tool_name",
                "tool_version",
            }:
                raise ValueError(
                    "Tool execution summaries must contain exactly tool_name and tool_version"
                )
            if not all(isinstance(value, str) for value in entry.values()):
                raise ValueError("Tool execution summary values must be strings")
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
    risk: Optional[str] = None
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

    The status lifecycle is:

    - ``received``: ingested and recorded, awaiting processing.
    - ``processing``: claimed by a pipeline processor (atomic transition
      from ``received``; at most one processor wins).
    - ``processed``: downstream execution completed successfully.
    - ``failed``: downstream execution failed; ``error_kind`` records
      the safe error category.

    ``processing``, ``processed``, and ``failed`` are terminal states
    for the current processing attempt. A stuck ``processing`` event
    (process crash) requires manual recovery.
    """

    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


@dataclass
class WebhookEvent:
    """Tenant-scoped record of one ingested webhook event (PRD 23 "Event").

    The record is deliberately metadata-only: it never stores the raw
    external payload. Webhook payloads are untrusted external input
    (ADR-001 webhook security boundary) and may contain PII; only safe
    envelope metadata is persisted:

    - which ingestion endpoint received the event (``endpoint_id``);
    - the tenant the event is bound to (``tenant_id``, resolved from the
      trusted endpoint configuration, NEVER from request input);
    - the sender-supplied unique event identifier (``event_id``), used
      for duplicate handling;
    - the event type label and payload size in bytes;
    - the processing status, optional error kind, and timestamps.
    """

    id: str
    tenant_id: str
    endpoint_id: str
    event_id: str
    event_type: str
    status: WebhookEventStatus = WebhookEventStatus.RECEIVED
    payload_size_bytes: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    error_kind: Optional[str] = None
    processed_at: Optional[datetime] = None

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


class ApiRequestMethod:
    """Allowed HTTP methods for telemetry records.

    A fixed allowlist (not free-form input): the middleware labels requests
    itself, and bounding the vocabulary keeps the stored column and every
    aggregate grouping within known, safe values.
    """

    ALLOWED = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


@dataclass
class ApiRequestRecord:
    """Metadata-only telemetry record for one HTTP request (TRD 17/28/31).

    Owned by the Observability/API layer. This is NOT a subsystem audit
    record: tool, connector, and webhook facts stay in their authoritative
    tables and are aggregated in place. This record stores ONLY:

    - the correlation ID minted by the request-telemetry middleware
      (``request_id``; distinct from future Agent execution IDs);
    - the tenant label applied by SUCCESS-GATED PATH-PARAM attribution:
      a request is labelled with a tenant ONLY when it resolved through
      an authenticated tenant route AND completed with status < 400.
      Attribution is telemetry bookkeeping and NEVER establishes tenant
      identity or authorization; unattributable/public requests store
      NULL;
    - the normalized route TEMPLATE (e.g. ``/tenants/{tenant_id}/tools``),
      never raw paths or query strings;
    - method, status code, monotonic-clock duration, coarse error class.

    NEVER persisted: request bodies, query strings, prompts, answers,
    credentials, tokens, secrets, PII, or arbitrary payload content
    (PRD 9/10, TRD 20/28).
    """

    id: str
    request_id: str
    method: str
    route_template: str
    status_code: int
    duration_ms: int
    tenant_id: Optional[str] = None
    error_kind: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("API request record ID cannot be empty")
        if len(self.id) > 255:
            raise ValueError("API request record ID cannot exceed 255 characters")
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValueError("Correlation request ID cannot be empty")
        if len(self.request_id) > 64:
            raise ValueError("Correlation request ID cannot exceed 64 characters")
        if not isinstance(self.method, str) or self.method not in ApiRequestMethod.ALLOWED:
            raise ValueError(f"Invalid HTTP method for telemetry record: {self.method!r}")
        if not isinstance(self.route_template, str) or not self.route_template:
            raise ValueError("Route template cannot be empty")
        if len(self.route_template) > 255:
            raise ValueError("Route template cannot exceed 255 characters")
        if "{" not in self.route_template and "?" in self.route_template:
            raise ValueError("Route template must not contain a query string")
        if not isinstance(self.status_code, int) or isinstance(self.status_code, bool):
            raise ValueError(f"Invalid HTTP status code: {self.status_code!r}")
        if not 100 <= self.status_code <= 599:
            raise ValueError(f"HTTP status code out of range: {self.status_code}")
        if not isinstance(self.duration_ms, int) or isinstance(self.duration_ms, bool):
            raise ValueError(f"Invalid request duration: {self.duration_ms!r}")
        if self.duration_ms < 0:
            raise ValueError("Request duration cannot be negative")
        if self.tenant_id is not None and (
            not isinstance(self.tenant_id, str) or not self.tenant_id
        ):
            raise ValueError("Attributed tenant ID must be a non-empty string when present")
        if self.error_kind is not None and (
            not isinstance(self.error_kind, str) or not self.error_kind
        ):
            raise ValueError("Error kind must be a non-empty string when present")


@dataclass
class HttpUsageMetrics:
    """Aggregate HTTP usage read-model (tenant-scoped or platform-wide).

    Numeric operational aggregates only: never per-tenant breakdowns,
    paths, or payload data.
    """

    total_requests: int
    error_count: int
    error_rate: float
    avg_duration_ms: float
    p95_duration_ms: float

    def __post_init__(self):
        if self.total_requests < 0 or self.error_count < 0:
            raise ValueError("HTTP metric counts cannot be negative")
        if self.error_count > self.total_requests:
            raise ValueError("HTTP error count cannot exceed total requests")
        if not 0.0 <= self.error_rate <= 1.0:
            raise ValueError("HTTP error rate must be between 0 and 1")
        if self.avg_duration_ms < 0 or self.p95_duration_ms < 0:
            raise ValueError("HTTP latency metrics cannot be negative")


@dataclass
class ToolExecutionActivityMetrics:
    """Aggregate AI Tool activity read-model over one source table."""

    total_executions: int
    successful: int
    failed: int
    denied: int

    def __post_init__(self):
        if min(self.total_executions, self.successful, self.failed, self.denied) < 0:
            raise ValueError("Tool activity counts cannot be negative")
        if self.successful + self.failed > self.total_executions:
            raise ValueError("Status breakdown cannot exceed total executions")


@dataclass
class ConnectorSyncActivityMetrics:
    """Aggregate connector sync activity read-model over one source table."""

    total_syncs: int
    successful: int
    failed: int
    items_fetched: int

    def __post_init__(self):
        if min(self.total_syncs, self.successful, self.failed, self.items_fetched) < 0:
            raise ValueError("Connector activity counts cannot be negative")
        if self.successful + self.failed > self.total_syncs:
            raise ValueError("Status breakdown cannot exceed total syncs")


@dataclass
class WebhookEventActivityMetrics:
    """Aggregate webhook event read-model.

    ``available`` reports whether the authoritative webhook_events table
    exists in this database. While the Webhooks foundation (PR #34) is
    unmerged, the table may legitimately be absent on main: Observability
    then reports zeros WITHOUT fabricating or duplicating the source.
    """

    available: bool
    total_events: int = 0
    distinct_event_types: int = 0
    total_payload_bytes: int = 0

    def __post_init__(self):
        if min(self.total_events, self.distinct_event_types, self.total_payload_bytes) < 0:
            raise ValueError("Webhook activity counts cannot be negative")


@dataclass
class ApprovalActivityMetrics:
    """Aggregate Human Intervention approval activity read-model.

    Counts are derived from the authoritative ``approval_requests`` table
    using DB-level status values.  Lazy-expired pending rows are counted
    as ``pending`` at the SQL level (consistent with how Observability
    aggregates authoritative subsystem state); the service layer handles
    lazy expiry on individual reads.
    """

    total: int
    pending: int
    approved: int
    rejected: int
    expired: int
    consumed: int

    def __post_init__(self):
        if (
            min(
                self.total,
                self.pending,
                self.approved,
                self.rejected,
                self.expired,
                self.consumed,
            )
            < 0
        ):
            raise ValueError("Approval activity counts cannot be negative")
        if self.pending + self.approved + self.rejected + self.expired + self.consumed > self.total:
            raise ValueError("Status breakdown cannot exceed total approvals")


class ApprovalStatus(str, Enum):
    """Lifecycle states of a Human Intervention approval request.

    Transitions (ADR-004 extension point; approved V1 contract):

        pending -> approved | rejected | expired   (terminal decisions)
        approved -> consumed                       (single-use execution gate)

    Terminal states are immutable: ``approved``/``rejected``/``expired``
    can never change again, and an approval is consumed AT MOST ONCE
    (replay fails). ``EXPIRED`` is applied lazily -- physically stored rows
    stay ``pending`` until a decision/consume attempt transitions them;
    reads derive expiry from ``expires_at`` without mutating state.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


@dataclass
class ApprovalRequest:
    """One Human Intervention approval request (V1 foundation).

    Created by the ToolExecutionService boundary when a tool's policy is
    ``REQUIRE_HUMAN_APPROVAL``. The row binds the EXACT validated request:

    - ``arguments_digest`` is the SHA-256 of the canonical JSON of the
      pydantic-VALIDATED arguments (same input model, same validation the
      execution path uses) -- computed only after validation succeeds, so
      an approval can never be consumed with materially different
      arguments. Raw arguments are NEVER persisted.
    - ``input_summary`` is the existing redacted/truncated summary.
    - Tenant binding comes exclusively from the trusted execution context.

    Lifecycle is single-use and fail-closed: see ``ApprovalStatus``.
    """

    id: str
    tenant_id: str
    requester_user_id: str
    tool_name: str
    tool_version: str
    risk_level: str
    input_summary: str
    arguments_digest: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default_factory=datetime.now)
    decided_at: Optional[datetime] = None
    decided_by_user_id: Optional[str] = None
    consumed_at: Optional[datetime] = None

    def __post_init__(self):
        import re

        if not self.id or len(self.id) > 255:
            raise ValueError(
                "Approval request ID must be a non-empty string of at most 255 characters"
            )
        if not self.tenant_id:
            raise ValueError("Approval request tenant ID cannot be empty")
        if not self.requester_user_id:
            raise ValueError("Approval requester user ID cannot be empty")
        if not self.tool_name or len(self.tool_name) > 255:
            raise ValueError(
                "Approval tool name must be a non-empty string of at most 255 characters"
            )
        if not self.tool_version or len(self.tool_version) > 50:
            raise ValueError(
                "Approval tool version must be a non-empty string of at most 50 characters"
            )
        if not isinstance(self.risk_level, str) or not self.risk_level:
            raise ValueError("Approval risk level must be a non-empty string")
        if not isinstance(self.input_summary, str) or not self.input_summary:
            raise ValueError("Approval input summary must be a non-empty string")
        if not isinstance(self.arguments_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.arguments_digest
        ):
            raise ValueError("Arguments digest must be a lowercase 64-character SHA-256 hex string")
        if not isinstance(self.status, ApprovalStatus):
            raise ValueError(f"Invalid approval status: {self.status!r}")
        if self.expires_at <= self.created_at:
            raise ValueError("Approval expiry must be after creation")
        terminal_requires_decision = {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.CONSUMED,
        }
        if self.status in terminal_requires_decision and (
            self.decided_at is None or not self.decided_by_user_id
        ):
            raise ValueError(
                "Approved/rejected/consumed approvals require decision metadata"
                " (decided_at and deciding user)"
            )
        if self.status == ApprovalStatus.CONSUMED and self.consumed_at is None:
            raise ValueError("Consumed approvals require consumed_at")
        if self.status == ApprovalStatus.PENDING and (
            self.decided_at is not None
            or self.decided_by_user_id is not None
            or self.consumed_at is not None
        ):
            raise ValueError("Pending approvals must not carry decision metadata")
        if self.status == ApprovalStatus.EXPIRED and (
            self.consumed_at is not None or self.decided_by_user_id is not None
        ):
            raise ValueError("Expired approvals must not carry a decider or consumption metadata")

    def effective_status(self, now: datetime) -> ApprovalStatus:
        """Lazy-expiry view: pending rows past their TTL read as EXPIRED."""
        if self.status == ApprovalStatus.PENDING and now >= self.expires_at:
            return ApprovalStatus.EXPIRED
        return self.status


class SkillExecutionStatus(str, Enum):
    """Terminal status of a Skill execution.

    ``SUCCEEDED`` means every proposed step ran. Every other value is a
    controlled, fail-closed outcome: nothing executes after a failure,
    and blocked executions (preconditions/approval) never execute at all.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PRECONDITION_FAILED = "precondition_failed"
    APPROVAL_REQUIRED = "approval_required"
    DENIED = "denied"


@dataclass
class SkillExecutionStepOutcome:
    """Outcome of exactly one proposed tool call within a Skill execution.

    A successful step carries its tool version and output; a failed step
    carries a safe ``error_kind`` instead. The two shapes are mutually
    exclusive so an outcome can never blur success and failure.
    """

    sequence: int
    tool_name: str
    status: ToolExecutionStatus
    tool_version: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    error_kind: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise ValueError("Step sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("Step sequence cannot be negative")
        if not isinstance(self.tool_name, str) or not self.tool_name:
            raise ValueError("Step tool name cannot be empty")
        if not isinstance(self.status, ToolExecutionStatus):
            raise ValueError(f"Invalid skill execution step status: {self.status!r}")
        if self.status is ToolExecutionStatus.SUCCESS:
            if self.error_kind is not None:
                raise ValueError("Successful steps cannot have an error kind")
            if self.output is None:
                raise ValueError("Successful steps must carry an output")
            if not self.tool_version:
                raise ValueError("Successful steps must record a tool version")
        elif self.status is ToolExecutionStatus.FAILED:
            if not self.error_kind:
                raise ValueError("Failed steps require an error kind")
            if self.output is not None:
                raise ValueError("Failed steps cannot carry an output")


@dataclass
class SkillExecutionResult:
    """Structured result of one Skill execution (controlled outcomes only).

    Terminal-state invariants are enforced fail closed:

    - ``SUCCEEDED`` carries no error kind and no failed steps.
    - Blocked executions (``PRECONDITION_FAILED``,
      ``APPROVAL_REQUIRED``) never record steps and always carry an
      error kind.
    - ``FAILED`` / ``DENIED`` always carry an error kind; their step
      list preserves the completed prefix plus the failing step.
    """

    id: str
    tenant_id: str
    principal_id: str
    skill_id: str
    skill_name: str
    skill_version: str
    status: SkillExecutionStatus
    steps: List[SkillExecutionStepOutcome] = field(default_factory=list)
    error_kind: Optional[str] = None
    approval_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Skill execution result ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Skill execution result tenant ID cannot be empty")
        if not self.principal_id:
            raise ValueError("Skill execution result principal ID cannot be empty")
        if not self.skill_id:
            raise ValueError("Skill execution result skill ID cannot be empty")
        if not self.skill_name:
            raise ValueError("Skill execution result skill name cannot be empty")
        if not self.skill_version:
            raise ValueError("Skill execution result skill version cannot be empty")
        if not isinstance(self.status, SkillExecutionStatus):
            raise ValueError(f"Invalid skill execution status: {self.status!r}")
        if not isinstance(self.steps, list) or not all(
            isinstance(step, SkillExecutionStepOutcome) for step in self.steps
        ):
            raise ValueError("steps must be a list of SkillExecutionStepOutcome instances")
        if self.status is SkillExecutionStatus.SUCCEEDED:
            if self.error_kind is not None:
                raise ValueError("Succeeded results cannot have an error kind")
            if any(step.status is ToolExecutionStatus.FAILED for step in self.steps):
                raise ValueError("Succeeded results cannot contain failed steps")
        elif self.status in (
            SkillExecutionStatus.PRECONDITION_FAILED,
            SkillExecutionStatus.APPROVAL_REQUIRED,
        ):
            if self.status is SkillExecutionStatus.APPROVAL_REQUIRED and self.approval_id:
                # Per-tool-call approval: steps before the approval gate
                # are permitted when an approval_id is present.
                pass
            elif self.steps:
                raise ValueError("Blocked results cannot record steps")
            if not self.error_kind:
                raise ValueError("Blocked results require an error kind")
        else:
            # FAILED and DENIED are terminal failure states.
            if not self.error_kind:
                raise ValueError("Failed or denied results requires an error kind")


class AgentRunStatus(str, Enum):
    """Terminal status of one bounded Agent run.

    ``SUCCEEDED`` means the Agent completed its goal through at least one
    successful Skill execution. Every other value is a controlled,
    fail-closed outcome: a Skill failure stops the run immediately (no
    retries), ``APPROVAL_REQUIRED`` propagates the engine's escalation
    state for the future Human Intervention capability, and
    ``MAX_STEPS_REACHED`` enforces the hard execution bound.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    APPROVAL_REQUIRED = "approval_required"
    MAX_STEPS_REACHED = "max_steps_reached"


@dataclass
class AgentStepOutcome:
    """Outcome of exactly one Skill execution attempted by the Agent.

    The step records the structured terminal status reported by
    ``SkillExecutionService``. A succeeded step carries no error kind;
    every non-succeeded step carries the safe error kind observed by the
    engine (or by the Agent's own decision boundary).
    """

    sequence: int
    skill_id: str
    skill_name: str
    status: SkillExecutionStatus
    error_kind: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise ValueError("Agent step sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("Agent step sequence cannot be negative")
        if not isinstance(self.skill_id, str) or not self.skill_id:
            raise ValueError("Agent step skill ID cannot be empty")
        if not isinstance(self.skill_name, str) or not self.skill_name:
            raise ValueError("Agent step skill name cannot be empty")
        if not isinstance(self.status, SkillExecutionStatus):
            raise ValueError(f"Invalid agent step status: {self.status!r}")
        if self.status is SkillExecutionStatus.SUCCEEDED:
            if self.error_kind is not None:
                raise ValueError("Succeeded agent steps cannot have an error kind")
        else:
            if not self.error_kind:
                raise ValueError("Non-succeeded agent steps require an error kind")


@dataclass
class AgentExecutionResult:
    """Structured result of one bounded Agent run (controlled outcomes only).

    Terminal-state invariants are enforced fail closed:

    - ``SUCCEEDED`` carries no error kind, at least one step, and only
      succeeded steps.
    - ``FAILED`` / ``APPROVAL_REQUIRED`` / ``MAX_STEPS_REACHED`` always
      carry a safe error kind; their step list preserves the executed
      prefix (decision-layer failures may record zero steps because no
      Skill ever ran).
    """

    id: str
    tenant_id: str
    principal_id: str
    goal: str
    status: AgentRunStatus
    steps: List[AgentStepOutcome] = field(default_factory=list)
    error_kind: Optional[str] = None
    approval_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Agent run result ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Agent run result tenant ID cannot be empty")
        if not self.principal_id:
            raise ValueError("Agent run result principal ID cannot be empty")
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise ValueError("Agent run goal cannot be empty")
        if not isinstance(self.status, AgentRunStatus):
            raise ValueError(f"Invalid agent run status: {self.status!r}")
        if not isinstance(self.steps, list) or not all(
            isinstance(step, AgentStepOutcome) for step in self.steps
        ):
            raise ValueError("steps must be a list of AgentStepOutcome instances")
        if self.status is AgentRunStatus.SUCCEEDED:
            if self.error_kind is not None:
                raise ValueError("Succeeded agent results cannot have an error kind")
            if not self.steps:
                raise ValueError("Succeeded agent results must contain at least one step")
            if any(step.status is not SkillExecutionStatus.SUCCEEDED for step in self.steps):
                raise ValueError("Succeeded agent results cannot contain unsuccessful steps")
        else:
            # FAILED, APPROVAL_REQUIRED, and MAX_STEPS_REACHED are terminal
            # controlled states.
            if not self.error_kind:
                raise ValueError("Non-succeeded agent results requires an error kind")


@dataclass(frozen=True)
class AgentDecision:
    """One untrusted LLM decision: which tenant Skill to run next.

    A decision is UNTRUSTED model output: a request that the application
    may validate against the trusted tenant's Skill catalog and execute
    exclusively through ``SkillExecutionService`` — never a grant. Use
    :meth:`parse` to strictly validate raw model output; anything that is
    not exactly this shape parses to ``None`` (fail closed, no coercion,
    no exception escapes).

    Deep structural validation of ``tool_calls`` remains owned by
    ``SkillExecutionService``: the decision boundary checks only enough
    shape to guarantee the proposal is a well-formed request.
    """

    skill_id: str
    tool_calls: List[Dict[str, Any]]
    satisfied_preconditions: List[str]

    MAX_SKILL_ID_LENGTH = 255
    _REQUIRED_KEYS = frozenset({"skill_id", "tool_calls", "satisfied_preconditions"})

    @classmethod
    def parse(cls, raw: Any) -> Optional["AgentDecision"]:
        """Strictly parse untrusted raw model output into a decision.

        Returns ``None`` (never raises) unless ``raw`` is exactly a
        mapping with exactly the keys ``skill_id`` (non-empty string of at
        most 255 characters), ``tool_calls`` (non-empty list of mapping
        objects), and ``satisfied_preconditions`` (list of strings).
        Unknown or missing fields are rejected; values are NOT coerced.
        """
        if not isinstance(raw, dict):
            return None
        if set(raw.keys()) != cls._REQUIRED_KEYS:
            return None
        skill_id = raw["skill_id"]
        tool_calls = raw["tool_calls"]
        preconditions = raw["satisfied_preconditions"]
        if not isinstance(skill_id, str) or not skill_id.strip():
            return None
        if len(skill_id) > cls.MAX_SKILL_ID_LENGTH:
            return None
        if not isinstance(tool_calls, list) or not tool_calls:
            return None
        if not all(isinstance(call, dict) for call in tool_calls):
            return None
        if not isinstance(preconditions, list) or not all(
            isinstance(condition, str) for condition in preconditions
        ):
            return None
        return cls(
            skill_id=skill_id,
            tool_calls=list(tool_calls),
            satisfied_preconditions=list(preconditions),
        )


@dataclass
class AgentRunRecordStep:
    """One step within a persisted agent execution trace.

    Stored as a JSONB array inside ``agent_run_records.steps``. Mirrors
    the ``AgentStepOutcome`` in-memory model but is a separate,
    persistence-oriented dataclass to keep the read/write models decoupled.
    """

    sequence: int
    skill_id: str
    skill_name: str
    status: str
    error_kind: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise ValueError("Agent run record step sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("Agent run record step sequence cannot be negative")
        if not isinstance(self.skill_id, str) or not self.skill_id:
            raise ValueError("Agent run record step skill_id cannot be empty")
        if not isinstance(self.skill_name, str) or not self.skill_name:
            raise ValueError("Agent run record step skill_name cannot be empty")
        if not isinstance(self.status, str) or not self.status:
            raise ValueError("Agent run record step status cannot be empty")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "sequence": self.sequence,
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "status": self.status,
        }
        if self.error_kind is not None:
            d["error_kind"] = self.error_kind
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentRunRecordStep":
        return cls(
            sequence=data["sequence"],
            skill_id=data["skill_id"],
            skill_name=data["skill_name"],
            status=data["status"],
            error_kind=data.get("error_kind"),
        )


@dataclass
class AgentRunRecord:
    """Persisted agent execution trace (PRD 17 O-6).

    Written by the Observability write path after each bounded Agent
    run completes. Provides queryable audit of which tenant, principal,
    goal, skill selections, tool invocations, and outcomes occurred.
    """

    id: str
    tenant_id: str
    principal_id: str
    goal: str
    status: str
    error_kind: Optional[str] = None
    steps: List[AgentRunRecordStep] = field(default_factory=list)
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.id:
            raise ValueError("Agent run record ID cannot be empty")
        if not self.tenant_id:
            raise ValueError("Agent run record tenant_id cannot be empty")
        if not self.principal_id:
            raise ValueError("Agent run record principal_id cannot be empty")
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise ValueError("Agent run record goal cannot be empty")
        if not isinstance(self.status, str) or not self.status:
            raise ValueError("Agent run record status cannot be empty")
        if not isinstance(self.steps, list) or not all(
            isinstance(step, AgentRunRecordStep) for step in self.steps
        ):
            raise ValueError("steps must be a list of AgentRunRecordStep instances")


@dataclass
class AgentRunActivityMetrics:
    """Aggregate agent run activity read-model over agent_run_records.

    Counts are derived from the authoritative ``agent_run_records``
    table using DB-level status filtering.
    """

    total_runs: int
    succeeded: int
    failed: int
    approval_required: int
    max_steps_reached: int

    def __post_init__(self):
        if (
            min(
                self.total_runs,
                self.succeeded,
                self.failed,
                self.approval_required,
                self.max_steps_reached,
            )
            < 0
        ):
            raise ValueError("Agent run activity counts cannot be negative")
        if (
            self.succeeded + self.failed + self.approval_required + self.max_steps_reached
            > self.total_runs
        ):
            raise ValueError("Status breakdown cannot exceed total runs")
