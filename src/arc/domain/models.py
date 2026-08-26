"""Domain models for multi-tenancy foundation."""

from dataclasses import dataclass, field
from datetime import datetime
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
            if self.steps:
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
