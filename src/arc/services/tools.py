"""AI Tools foundation: platform-owned registry and controlled execution.

This module implements the AI Tools slice of the approved architecture
(PRD 15, TRD 14, ADR-001):

- The tool catalog is a **platform-owned, code-defined whitelist**. Tenants
  cannot register tools, upload executable code, or define executable
  handlers. The registry exposes no runtime registration or mutation
  API: the approved catalog is closed by construction. Tenants gain
  tenant-scoped access to the platform-owned AI Tool catalog exclusively
  through the existing authorization model (``tool:read``,
  ``tool:execute``, and each tool's declared required permissions).
- Execution follows TRD 14.1: selection -> authorization (``tool:execute``
  AND every permission declared by the tool, enforced fail-closed inside
  this service using the existing permission machinery) -> tool policy
  check -> input validation -> execution -> result handling ->
  execution/audit record. Every controlled attempt produces an observable
  tenant-scoped record (TRD 14.2), including controlled failures and
  authorization denials.
- There is no path for arbitrary Python/OS/shell/database/network
  execution: handlers are plain whitelisted functions, inputs are
  validated against the tool's declared schema before any handler runs,
  and unknown tool names fail closed without any dynamic lookup.
- The design remains framework/tool agnostic (TRD 14.3, ADR-001): no
  third-party AI-agent/tool framework is introduced. Input/output
  validation reuses the project's existing pydantic/FastAPI schema
  pattern; the catalog exposes declarative JSON Schemas.

The security boundary intentionally does NOT trust the caller: the
tenant boundary comes exclusively from the trusted ``TenantContext``,
and per-tool authorization is enforced fail-closed inside the service
using the application's existing ``AuthorizationService`` before any
handler can run.

Audit ownership boundary:

- Central authentication/RBAC failure (401/403 raised by the FastAPI
  security dependencies before this service runs, for example a caller
  without ``tool:execute``) is owned by the central security boundary:
  ``ToolExecutionService`` is NOT invoked and no
  ``tool_execution_records`` row is written, because there is no
  controlled tool attempt to attribute.
- Per-tool authorization failure (the caller holds ``tool:execute`` but
  lacks a permission declared by the tool) is owned by this service:
  the attempt is refused fail-closed inside ``execute_tool`` and the
  denial is recorded with ``authorization_outcome=DENIED``.
"""

import json
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, ValidationError

from arc.domain.models import (
    TenantContext,
    ToolAuthorizationOutcome,
    ToolExecutionRecord,
    ToolExecutionStatus,
    ToolRiskLevel,
)
from arc.security.authorization import TOOL_EXECUTE, AuthorizationService
from arc.security.models import AuthenticatedPrincipal, Permission

# ---------------------------------------------------------------------------
# Controlled failure types
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Base error for controlled AI Tool failures."""


class ToolNotFoundError(ToolError):
    """Raised when the requested tool is not in the platform-approved catalog."""


class ToolValidationError(ToolError):
    """Raised when tool input fails validation; the handler is never invoked."""


class ToolDeniedError(ToolError):
    """Raised when the attempt is denied by authorization or policy.

    Denial is fail-closed and happens before any handler can run:
    insufficient or invalid permission metadata, missing required
    permissions, or an execution policy that forbids direct execution.
    """


class ToolExecutionError(ToolError):
    """Raised when a platform-approved handler fails during execution."""


# ---------------------------------------------------------------------------
# Registry primitives
# ---------------------------------------------------------------------------


class ToolExecutionPolicyMode(str, Enum):
    """Execution policy of an approved tool (TRD 17.3 boundary).

    The policy explicitly represents three states so that a high-risk
    tool can never silently bypass the approval policy:

    - ``ALLOW``: an authorized caller may execute the tool directly.
    - ``DENY``: direct execution is refused (fail closed).
    - ``REQUIRE_HUMAN_APPROVAL``: execution is refused until a human
      approval gate exists; the Human Intervention capability is NOT
      implemented in this slice, so this mode always fails closed with
      a controlled denial instead of executing.
    """

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HUMAN_APPROVAL = "require_human_approval"


@dataclass(frozen=True)
class ToolExecutionPolicy:
    """Policy that constrains how an approved tool may be executed.

    ``mode`` gates execution by any authorized caller. High-risk tools
    (``ToolRiskLevel.HIGH``) must declare ``REQUIRE_HUMAN_APPROVAL`` or
    ``DENY``: the catalog build rejects a high-risk tool with ``ALLOW``
    so the approval policy can never be silently bypassed. The
    human-approval gate itself is part of the Human Intervention
    capability and is not implemented here; until it exists, that mode
    fails closed.
    """

    mode: ToolExecutionPolicyMode = ToolExecutionPolicyMode.ALLOW


@dataclass(frozen=True)
class ToolAuditPolicy:
    """Policy that constrains what an approved tool records (TRD 14.2).

    Only safe, sanitized summaries are ever persisted: never secrets,
    credentials, raw sensitive payloads, or internal stack traces.
    """

    record_summary_only: bool = True


@dataclass(frozen=True)
class ToolDefinition:
    """Declarative definition of one platform-approved AI Tool (PRD 15).

    Every approved tool declares its purpose, version, input/output
    schemas, required permissions, risk level, execution policy, audit
    policy, and a whitelisted in-process handler. The schema metadata is
    exposed as framework-agnostic JSON Schemas; the handler is a plain
    platform-owned function and is never exposed.

    The definition fails closed at construction:

    - ``required_permissions`` must be a non-empty set of ``Permission``
      objects (missing, empty, or invalid metadata is rejected);
    - a high-risk tool must declare ``REQUIRE_HUMAN_APPROVAL`` or ``DENY``
      as its execution policy, never ``ALLOW``.
    """

    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    required_permissions: FrozenSet[Permission]
    risk_level: ToolRiskLevel
    execution_policy: ToolExecutionPolicy
    audit_policy: ToolAuditPolicy
    handler: Callable[[Dict[str, Any], str], Dict[str, Any]]

    def __post_init__(self):
        if not self.name:
            raise ValueError("Tool name cannot be empty")
        if not self.version:
            raise ValueError("Tool version cannot be empty")
        if not self.required_permissions:
            raise ValueError(f"Tool {self.name!r} must declare at least one required permission")
        if not all(isinstance(p, Permission) for p in self.required_permissions):
            raise ValueError(
                f"Tool {self.name!r} declares invalid permission metadata "
                "(all required_permissions entries must be Permission objects)"
            )
        if (
            self.risk_level == ToolRiskLevel.HIGH
            and self.execution_policy.mode == ToolExecutionPolicyMode.ALLOW
        ):
            raise ValueError(
                f"Tool {self.name!r} is high-risk and must not be directly "
                "executable without a human approval gate"
            )

    @property
    def input_schema(self) -> Dict[str, Any]:
        """JSON Schema describing the tool's accepted input."""
        return self.input_model.model_json_schema()

    @property
    def output_schema(self) -> Dict[str, Any]:
        """JSON Schema describing the tool's output."""
        return self.output_model.model_json_schema()


class ToolRegistry:
    """Platform-owned, closed whitelist of approved AI Tools.

    The registry is built once from the code-defined catalog and exposes
    only read operations. There is no registration or mutation API: a
    tool is executable if and only if it is part of this static whitelist.
    """

    def __init__(self, tools: Optional[Mapping[str, ToolDefinition]] = None):
        self._tools: Dict[str, ToolDefinition] = dict(tools) if tools else {}

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Return the approved tool definition for ``name``, or None."""
        return self._tools.get(name)

    def list(self) -> List[ToolDefinition]:
        """Return the approved tool definitions in catalog order."""
        return list(self._tools.values())

    def names(self) -> FrozenSet[str]:
        """Return the set of approved tool names."""
        return frozenset(self._tools.keys())


# ---------------------------------------------------------------------------
# Summary sanitization (TRD 14.2: safe, sanitized execution records)
# ---------------------------------------------------------------------------


_SENSITIVE_KEYS: FrozenSet[str] = frozenset(
    {
        "password",
        "passwd",
        "token",
        "secret",
        "api_key",
        "apikey",
        "access_key",
        "access_token",
        "refresh_token",
        "private_key",
        "client_secret",
        "authorization",
        "credential",
        "credentials",
    }
)


def _redact(value: Any) -> Any:
    """Replace the values of sensitive-keyed entries with a safe marker.

    Data minimization for execution records (TRD 14.2): values under
    keys such as ``password``, ``token``, ``api_key``, ``secret``,
    ``access_token``, ``client_secret``, or ``authorization`` are never
    persisted, only a ``[REDACTED]`` marker. Key matching is
    case-insensitive and applied at every nesting depth (objects,
    arrays, and deeply nested structures).

    Redaction policy for free-form text: only keyed values are redacted.
    Arbitrary free-form strings inside values (for example a sentence
    containing the word ``secret``) are intentionally retained, because
    heuristic secret scanning is unreliable; the summaries that reach
    this function are bounded by platform-owned handlers and validated
    input models, and any secret that arrives under a sensitive key is
    always removed.
    """
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _summarize(value: Any, max_length: int = 512) -> str:
    """Return a safe, truncated summary of a value for an execution record.

    Values are redacted (sensitive keys, at any nesting depth),
    JSON-encoded, and truncated so records never contain raw sensitive
    payloads, secrets, or implementation details.

    If the redacted value cannot be JSON-encoded (for example a
    self-referential structure or a dict with non-string keys), the
    fallback is a fixed safe classification marker instead of a raw
    ``str()``: ``str()`` of an unserializable structure can contain
    sensitive values and would bypass the keyed redaction policy.
    """
    try:
        encoded = json.dumps(_redact(value), sort_keys=True, default=str, ensure_ascii=True)
    except (TypeError, ValueError, RecursionError):
        encoded = f"[unserializable {type(value).__name__} payload redacted]"
    return encoded[:max_length]


# ---------------------------------------------------------------------------
# Platform-approved catalog
# ---------------------------------------------------------------------------


class ServiceHealthInput(BaseModel):
    """Input for ``check_service_health``: no parameters are accepted."""

    model_config = ConfigDict(extra="forbid")


class ServiceHealthEntry(BaseModel):
    """Simulated health of one Arc internal service."""

    name: str
    status: str


class ServiceHealthOutput(BaseModel):
    """Output of ``check_service_health``.

    ``tenant_id`` is echoed from the trusted tenant context, never from
    caller input.
    """

    tenant_id: str
    services: List[ServiceHealthEntry]


# Controlled/simulated implementation permitted by TRD 33: the health
# monitoring subsystem is a separate Person C slice; this tool returns a
# deterministic synthetic health snapshot for Arc's simulated services.
_SIMULATED_SERVICES: Tuple[Tuple[str, str], ...] = (
    ("api-gateway", "healthy"),
    ("knowledge-service", "healthy"),
    ("webhook-service", "healthy"),
)


def _check_service_health_handler(input_data: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """Platform-approved handler for ``check_service_health``.

    Deterministic and tenant-scoped: the result is derived only from the
    trusted tenant context and fixed synthetic service state.
    """
    return {
        "tenant_id": tenant_id,
        "services": [{"name": name, "status": status} for name, status in _SIMULATED_SERVICES],
    }


SERVICE_HEALTH_TOOL = ToolDefinition(
    name="check_service_health",
    version="1",
    description=(
        "Check the health of Arc's simulated internal services for the "
        "trusted tenant (controlled/simulated implementation, TRD 33)."
    ),
    input_model=ServiceHealthInput,
    output_model=ServiceHealthOutput,
    required_permissions=frozenset({TOOL_EXECUTE}),
    risk_level=ToolRiskLevel.LOW,
    execution_policy=ToolExecutionPolicy(),
    audit_policy=ToolAuditPolicy(record_summary_only=True),
    handler=_check_service_health_handler,
)

PLATFORM_TOOLS: Tuple[ToolDefinition, ...] = (SERVICE_HEALTH_TOOL,)


def build_platform_tool_registry() -> ToolRegistry:
    """Build the platform-owned registry from the approved catalog."""
    return ToolRegistry({tool.name: tool for tool in PLATFORM_TOOLS})


# ---------------------------------------------------------------------------
# Execution service
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolExecutionResult:
    """Outcome of a controlled tool execution."""

    tool_name: str
    tool_version: str
    output: Dict[str, Any]


class ToolExecutionService:
    """Controlled AI Tool execution (TRD 14.1) with observable records.

    The service accepts a trusted ``TenantContext`` established by X-10
    and derives the tenant boundary exclusively from it; the caller-
    supplied path ``tenant_id`` is never an authority here. Per-tool
    authorization is enforced fail-closed INSIDE this service using the
    application's existing ``AuthorizationService`` and the authenticated
    principal: the caller must hold ``tool:execute`` AND every permission
    declared by the tool, otherwise the attempt is denied before any
    handler can run.
    """

    def __init__(self, registry: ToolRegistry, record_repo):
        self.registry = registry
        self.record_repo = record_repo

    def list_tools(self, context: TenantContext) -> List[ToolDefinition]:
        """Return the platform-owned AI Tool catalog for the trusted tenant.

        The catalog is platform-owned, versioned, and identical for every
        tenant; tenants gain tenant-scoped access to it exclusively
        through the existing authorization model. The trusted context is
        required so the listing is always made inside an authenticated,
        tenant-scoped request.
        """
        return self.registry.list()

    async def execute_tool(
        self,
        context: TenantContext,
        principal: AuthenticatedPrincipal,
        tool_name: str,
        raw_input: Dict[str, Any],
        authorization: AuthorizationService,
    ) -> ToolExecutionResult:
        """Execute an approved tool following the TRD 14.1 flow.

        Flow: selection -> authorization (``tool:execute`` AND every
        declared required permission, fail closed) -> tool policy check ->
        input validation -> execution -> result handling -> execution/
        audit record. Every controlled attempt, including controlled
        failures and authorization denials, produces an observable
        tenant-scoped record.
        """
        if context is None or not context.is_valid:
            # Fail closed with no record: there is no trusted tenant to
            # attribute an audit record to.
            raise ToolDeniedError(tool_name)

        tool = self.registry.get(tool_name)
        if tool is None:
            await self._record_failure(
                context=context,
                user_id=principal.user_id,
                authorization_outcome=ToolAuthorizationOutcome.DENIED,
                tool_name=tool_name,
                tool_version="unknown",
                risk_level=ToolRiskLevel.LOW,
                input_summary=_summarize(raw_input),
                error_kind="unknown_tool",
            )
            raise ToolNotFoundError(tool_name)

        if not self._authorized(tool, principal, authorization):
            if not tool.required_permissions or not all(
                isinstance(p, Permission) for p in tool.required_permissions
            ):
                error_kind = "invalid_permission_metadata"
            else:
                error_kind = "authorization_denied"
            await self._record_failure(
                context=context,
                user_id=principal.user_id,
                authorization_outcome=ToolAuthorizationOutcome.DENIED,
                tool_name=tool.name,
                tool_version=tool.version,
                risk_level=tool.risk_level,
                input_summary=_summarize(raw_input),
                error_kind=error_kind,
            )
            raise ToolDeniedError(tool_name)

        policy_outcome = tool.execution_policy.mode
        if (
            tool.risk_level == ToolRiskLevel.HIGH
            and policy_outcome == ToolExecutionPolicyMode.ALLOW
        ):
            # Defense in depth: a high-risk tool must never silently
            # bypass the approval policy, even if a malformed definition
            # somehow bypassed catalog validation.
            await self._record_failure(
                context=context,
                user_id=principal.user_id,
                authorization_outcome=ToolAuthorizationOutcome.GRANTED,
                tool_name=tool.name,
                tool_version=tool.version,
                risk_level=tool.risk_level,
                input_summary=_summarize(raw_input),
                error_kind="invalid_policy_metadata",
            )
            raise ToolDeniedError(tool_name)
        if policy_outcome == ToolExecutionPolicyMode.DENY:
            await self._record_failure(
                context=context,
                user_id=principal.user_id,
                authorization_outcome=ToolAuthorizationOutcome.GRANTED,
                tool_name=tool.name,
                tool_version=tool.version,
                risk_level=tool.risk_level,
                input_summary=_summarize(raw_input),
                error_kind="not_allowed",
            )
            raise ToolDeniedError(tool_name)
        if policy_outcome == ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL:
            # Human Intervention is not implemented: fail closed rather
            # than silently bypassing the approval policy.
            await self._record_failure(
                context=context,
                user_id=principal.user_id,
                authorization_outcome=ToolAuthorizationOutcome.GRANTED,
                tool_name=tool.name,
                tool_version=tool.version,
                risk_level=tool.risk_level,
                input_summary=_summarize(raw_input),
                error_kind="requires_human_approval",
            )
            raise ToolDeniedError(tool_name)

        try:
            validated = tool.input_model.model_validate(raw_input)
        except ValidationError:
            await self._record_failure(
                context=context,
                user_id=principal.user_id,
                authorization_outcome=ToolAuthorizationOutcome.GRANTED,
                tool_name=tool.name,
                tool_version=tool.version,
                risk_level=tool.risk_level,
                input_summary=_summarize(raw_input),
                error_kind="invalid_input",
            )
            raise ToolValidationError(tool_name)

        input_data = validated.model_dump()

        try:
            output = tool.handler(input_data, context.tenant_id)
        except Exception:
            await self._record_failure(
                context=context,
                user_id=principal.user_id,
                authorization_outcome=ToolAuthorizationOutcome.GRANTED,
                tool_name=tool.name,
                tool_version=tool.version,
                risk_level=tool.risk_level,
                input_summary=_summarize(input_data),
                error_kind="execution_error",
            )
            raise ToolExecutionError(tool_name)

        await self._record_success(
            context=context,
            user_id=principal.user_id,
            tool=tool,
            input_summary=_summarize(input_data),
            output_summary=_summarize(output),
        )
        return ToolExecutionResult(
            tool_name=tool.name,
            tool_version=tool.version,
            output=output,
        )

    def _authorized(
        self,
        tool: ToolDefinition,
        principal: AuthenticatedPrincipal,
        authorization: AuthorizationService,
    ) -> bool:
        """Fail-closed per-tool authorization check.

        Grants execution only when the caller holds ``tool:execute`` AND
        every permission declared by the tool. Missing, empty, or
        invalid permission metadata denies the attempt.
        """
        if not tool.required_permissions:
            return False
        if not all(isinstance(p, Permission) for p in tool.required_permissions):
            return False
        if not authorization.has_permission(principal, TOOL_EXECUTE):
            return False
        return all(
            authorization.has_permission(principal, permission)
            for permission in tool.required_permissions
        )

    async def _record_success(
        self,
        context: TenantContext,
        user_id: str,
        tool: ToolDefinition,
        input_summary: str,
        output_summary: str,
    ) -> None:
        await self.record_repo.create_record(
            ToolExecutionRecord(
                id=str(uuid.uuid4()),
                tenant_id=context.tenant_id,
                user_id=user_id,
                tool_name=tool.name,
                tool_version=tool.version,
                status=ToolExecutionStatus.SUCCESS,
                authorization_outcome=ToolAuthorizationOutcome.GRANTED,
                risk_level=tool.risk_level,
                input_summary=input_summary,
                output_summary=output_summary,
            )
        )

    async def _record_failure(
        self,
        context: TenantContext,
        user_id: str,
        authorization_outcome: ToolAuthorizationOutcome,
        tool_name: str,
        tool_version: str,
        risk_level: ToolRiskLevel,
        input_summary: str,
        error_kind: str,
    ) -> None:
        await self.record_repo.create_record(
            ToolExecutionRecord(
                id=str(uuid.uuid4()),
                tenant_id=context.tenant_id,
                user_id=user_id,
                tool_name=tool_name,
                tool_version=tool_version,
                status=ToolExecutionStatus.FAILED,
                authorization_outcome=authorization_outcome,
                risk_level=risk_level,
                input_summary=input_summary,
                error_kind=error_kind,
            )
        )
