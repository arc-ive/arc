"""Typed request contracts for the Arc HTTP API (Issue #135).

Each model captures the request body an endpoint already accepted, so that
FastAPI validates and documents it instead of the handler hand-checking a
``Dict[str, Any]``. Defaults and optionality mirror the previous hand-written
behaviour exactly: these models are meant to describe the existing contract,
not to tighten it.

Two deliberate exceptions, both fixing unhandled 500s: a required field that
was previously read with ``.get()`` and passed to a domain constructor is now
declared required, and required strings carry ``min_length=1`` because the
domain models reject empty strings in ``__post_init__``.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from arc.domain.models import (
    ConnectorProvider,
    KnowledgeSource,
    KnowledgeStatus,
    SkillRiskLevel,
    SkillStatus,
    ToolExecutionStatus,
    UserRole,
)


def _reject_explicit_nulls(model: BaseModel, fields: tuple[str, ...]) -> None:
    """Reject fields that were sent explicitly as null.

    Omitting a key on a partial update keeps the stored value, but sending
    ``null`` is a value, and the domain models refuse it. Without this the null
    reaches a dataclass constructor outside the handler's try/except and
    surfaces as a 500 instead of a validation error.
    """
    for name in fields:
        if name in model.model_fields_set and getattr(model, name) is None:
            raise ValueError(f"{name} must not be null")


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------


class TenantCreateRequest(BaseModel):
    """Body of ``POST /tenants``."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: str = "active"


class TenantUpdateRequest(BaseModel):
    """Body of ``PUT /tenants/{tenant_id}``.

    Every field is optional: an omitted key leaves the stored value untouched.
    ``status`` is deliberately absent — the endpoint has never allowed a client
    to change it, and a test asserts that.

    Unknown fields are rejected, for the same reason issue #236 rejected
    them on tool execution. Without this, ``{"status": "suspended"}``
    returned 200 with the status unchanged: the caller was told their
    change succeeded when nothing happened, which is worse than a refusal
    because there is no symptom. A typo in a field name behaved the same
    way. Deactivating a tenant is a real gap (issue #295); answering the
    attempt with a silent success is a defect.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1)
    industry: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None

    @model_validator(mode="after")
    def _check_nulls(self):
        _reject_explicit_nulls(self, ("name",))
        return self


# ---------------------------------------------------------------------------
# Users and memberships
# ---------------------------------------------------------------------------


class UserCreateRequest(BaseModel):
    """Body of ``POST /users``."""

    id: str = Field(min_length=1)
    email: str = Field(min_length=1)
    username: Optional[str] = None
    status: str = "active"


class MembershipCreateRequest(BaseModel):
    """Body of ``POST /tenants/{tenant_id}/memberships``."""

    user_id: str = Field(min_length=1)
    role: UserRole = UserRole.MEMBER


class DevMembershipCreateRequest(BaseModel):
    """Body of the development-only membership provisioning endpoint.

    ``user_id`` is a path parameter there, not a body field, so this is a
    separate model rather than a reuse of ``MembershipCreateRequest``.
    """

    role: UserRole = UserRole.MEMBER
    id: Optional[str] = None


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


class SkillCreateRequest(BaseModel):
    """Body of ``POST /tenants/{tenant_id}/skills``.

    Field defaults mirror ``Skill``'s own dataclass defaults, so a minimal
    request produces the same Skill it did before this model existed.
    """

    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    version: str = Field(default="1", min_length=1)
    inputs: List[str] = Field(default_factory=list)
    preconditions: List[str] = Field(default_factory=list)
    steps: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    allowed_tools: List[str] = Field(default_factory=list)
    # StrictBool mirrors Skill.__post_init__, which requires a real bool.
    approval_required: StrictBool = False
    expected_output: Optional[str] = None
    failure_behavior: Optional[str] = None
    provenance: Optional[str] = None
    risk: Optional[SkillRiskLevel] = None
    status: SkillStatus = SkillStatus.ACTIVE


class SkillUpdateRequest(BaseModel):
    """Body of ``PUT /tenants/{tenant_id}/skills/{skill_id}``.

    Every field is optional; an omitted key keeps the stored value.
    """

    name: Optional[str] = Field(default=None, min_length=1)
    purpose: Optional[str] = Field(default=None, min_length=1)
    version: Optional[str] = Field(default=None, min_length=1)
    inputs: Optional[List[str]] = None
    preconditions: Optional[List[str]] = None
    steps: Optional[List[str]] = None
    constraints: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None
    approval_required: Optional[StrictBool] = None
    expected_output: Optional[str] = None
    failure_behavior: Optional[str] = None
    provenance: Optional[str] = None
    risk: Optional[SkillRiskLevel] = None
    status: Optional[SkillStatus] = None

    @model_validator(mode="after")
    def _check_nulls(self):
        _reject_explicit_nulls(self, ("name", "purpose", "version", "status"))
        return self


# ---------------------------------------------------------------------------
# Skill and agent execution
# ---------------------------------------------------------------------------


class SkillExecuteRequest(BaseModel):
    """Body of ``POST /tenants/{tenant_id}/skills/{skill_id}/execute``.

    Deliberately loose: the handler only ever required the body to be a JSON
    object, and ``SkillExecutionService`` owns validation of the tool calls
    themselves. Typing them here would tighten the contract, not describe it.
    """

    tool_calls: Optional[Any] = None
    satisfied_preconditions: Any = Field(default_factory=list)
    skill_inputs: Any = None


class PreviousStepInput(BaseModel):
    """One already-executed step replayed into a resumed execution.

    These entries were previously read by direct dictionary indexing outside
    any try/except, so a missing key or an unknown ``status`` produced a 500.
    The field constraints and the cross-field rules below mirror
    ``SkillExecutionStepOutcome.__post_init__``: anything it rejects has to be
    rejected here, or it still reaches the dataclass and still returns a 500.
    """

    # StrictInt because the dataclass rejects bool explicitly, and bool is a
    # subclass of int.
    sequence: StrictInt = Field(ge=0)
    tool_name: str = Field(min_length=1)
    status: ToolExecutionStatus
    tool_version: Optional[str] = None
    output: Optional[Any] = None
    error_kind: Optional[str] = None

    @model_validator(mode="after")
    def _check_status_invariants(self):
        if self.status is ToolExecutionStatus.SUCCESS:
            if self.error_kind is not None:
                raise ValueError("successful steps cannot have an error kind")
            if self.output is None:
                raise ValueError("successful steps must carry an output")
            if not self.tool_version:
                raise ValueError("successful steps must record a tool version")
        elif self.status is ToolExecutionStatus.FAILED:
            if not self.error_kind:
                raise ValueError("failed steps require an error kind")
            if self.output is not None:
                raise ValueError("failed steps cannot carry an output")
        return self


class SkillResumeRequest(BaseModel):
    """Body of ``POST /tenants/{tenant_id}/skills/{skill_id}/resume``."""

    approval_id: str = Field(min_length=1)
    tool_calls: List[Any] = Field(min_length=1)
    resume_from_step: StrictInt = Field(ge=0)
    previous_steps: List[PreviousStepInput] = Field(default_factory=list)
    satisfied_preconditions: Any = Field(default_factory=list)
    skill_inputs: Any = None


class AgentRunRequest(BaseModel):
    """Body of ``POST /agent/runs``.

    ``goal`` stays untyped: the handler passes it to the agent service
    without inspecting it.

    ``tenant_id`` is declared so the field appears in the generated document,
    but its constraint never fires: ``_require_tenant_permission_from_body``
    is a sub-dependency, and FastAPI resolves sub-dependencies before the
    route's own body, so a missing or empty ``tenant_id`` is already rejected
    there with a 400 and a string detail. Moving that check into this model
    would change an authorization-boundary error, which is out of scope here.
    """

    tenant_id: str = Field(min_length=1)
    goal: Optional[Any] = None


class AgentResumeRequest(BaseModel):
    """Body of ``POST /agent/runs/resume``.

    See ``AgentRunRequest`` on why ``tenant_id``'s constraint is unreachable.
    """

    tenant_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    tool_calls: List[Any] = Field(min_length=1)
    resume_from_step: StrictInt = Field(ge=0)
    previous_steps: List[PreviousStepInput] = Field(default_factory=list)
    satisfied_preconditions: Any = Field(default_factory=list)
    skill_inputs: Any = None


# ---------------------------------------------------------------------------
# Knowledge and intelligence
# ---------------------------------------------------------------------------


class KnowledgeCreateRequest(BaseModel):
    """Body of ``POST /tenants/{tenant_id}/knowledge``."""

    source: KnowledgeSource
    provenance: str = Field(min_length=1)
    content: str = Field(min_length=1)
    version: StrictInt = 1
    external_id: Optional[str] = None


class KnowledgeUpdateRequest(BaseModel):
    """Body of ``PUT /tenants/{tenant_id}/knowledge/{document_id}``.

    Every field is optional; an omitted key keeps the stored value.
    ``version`` and ``external_id`` are not editable: version is managed
    by the service layer and external_id is the connector identity key.
    """

    source: Optional[KnowledgeSource] = None
    provenance: Optional[str] = Field(default=None, min_length=1)
    content: Optional[str] = Field(default=None, min_length=1)
    status: Optional[KnowledgeStatus] = None


class IntelligenceQueryRequest(BaseModel):
    """Body of ``POST /tenants/{tenant_id}/intelligence/query``.

    ``limit`` keeps the previous 1-50 bound. Rejecting a boolean ``limit``
    was explicit in the hand-written check this replaces, because ``bool`` is
    a subclass of ``int``; Pydantic enforces the same distinction.
    """

    query: str = Field(min_length=1)
    # StrictInt, not int: Pydantic would otherwise accept True as 1 and any
    # numeric string, where the check this replaces admitted genuine ints only.
    limit: StrictInt = Field(default=5, ge=1, le=50)
    # Optional corpus scoping: restricts retrieval to one KnowledgeSource.
    # Unknown values are rejected by pydantic before any retrieval runs.
    source_type: Optional[KnowledgeSource] = None

    @field_validator("query")
    @classmethod
    def _reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


# ---------------------------------------------------------------------------
# Connectors, approvals, tools
# ---------------------------------------------------------------------------


class ConnectorCreateRequest(BaseModel):
    """Body of ``POST /tenants/{tenant_id}/connectors``."""

    provider: ConnectorProvider
    name: str = Field(min_length=1)
    target: str = ""


class ApprovalDecisionRequest(BaseModel):
    """Body of ``POST /tenants/{tenant_id}/approvals/{approval_id}/decisions``."""

    decision: Literal["approve", "reject"]


class ToolExecuteRequest(BaseModel):
    """Envelope of ``POST /tenants/{tenant_id}/tools/{name}/execute``.

    ``input`` stays untyped on purpose: the route dispatches by tool name and
    each tool validates its own payload against its ``input_model`` inside
    ``ToolExecutionService``. Only the envelope is a fixed contract.
    Unknown envelope fields are rejected so a wrong key (e.g.
    ``parameters``) fails instead of silently executing with empty input.
    """

    model_config = ConfigDict(extra="forbid")

    input: Dict[str, Any] = Field(default_factory=dict)
    approval_id: Optional[str] = None


__all__ = [
    "TenantCreateRequest",
    "TenantUpdateRequest",
    "UserCreateRequest",
    "MembershipCreateRequest",
    "DevMembershipCreateRequest",
    "SkillCreateRequest",
    "SkillUpdateRequest",
    "SkillExecuteRequest",
    "SkillResumeRequest",
    "PreviousStepInput",
    "AgentRunRequest",
    "AgentResumeRequest",
    "KnowledgeCreateRequest",
    "KnowledgeUpdateRequest",
    "IntelligenceQueryRequest",
    "ConnectorCreateRequest",
    "ApprovalDecisionRequest",
    "ToolExecuteRequest",
    "AUTHENTICATED_ERROR_RESPONSES",
    "AUTHENTICATION_ONLY_ERROR_RESPONSES",
]


# ---------------------------------------------------------------------------
# OpenAPI error declarations
# ---------------------------------------------------------------------------

ERROR_DETAIL_SCHEMA = {
    "type": "object",
    "properties": {"detail": {"type": "string"}},
}

#: Errors every RBAC-protected route can return. Declared on the router so the
#: generated document reflects them without repeating the same block on each
#: of the routes. FastAPI already documents 422 by itself for any route with a
#: validatable body or parameter, so it is deliberately not repeated here.
#: For routes that authenticate but run no permission check, so 403 never
#: applies to them: session-scoped auth routes and HMAC-signed webhook intake.
AUTHENTICATION_ONLY_ERROR_RESPONSES = {
    401: {
        "description": "Authentication is missing or invalid.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    },
}

AUTHENTICATED_ERROR_RESPONSES = {
    401: {
        "description": "Authentication is missing or invalid.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    },
    403: {
        "description": "The caller lacks the required permission, or the "
        "requested tenant is outside their membership.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    },
}
