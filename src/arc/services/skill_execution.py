"""Skill execution engine for Arc (controlled, deterministic, secure).

Implements the execution half of the Skills Engine (PRD 13, TRD 13/25,
ADR-001): a declared Skill becomes an executable workflow whose ONLY
action path is the existing ``ToolExecutionService``. This service is the
controlled boundary a future AI Agent will orchestrate; the Agent must
never bypass it, and it never bypasses the tool layer.

Execution flow (fail closed at every gate)::

    Trusted TenantContext (X-10) + skill:execute permission
        |
        v
    resolve Skill (tenant-scoped repository via SkillService)
        |
        v
    Skill executable? (status ACTIVE)          no -> FAILED/inactive_skill
        |
        v
    preconditions satisfied?                   no -> PRECONDITION_FAILED
        |
        v
    Skill.approval_required?                   yes -> APPROVAL_REQUIRED
        |                                            (fail closed; the Human
        |                                             Intervention capability
        |                                             is not implemented)
        v
    for each proposed tool call (in order):
        allowed by Skill.allowed_tools?         no  -> DENIED/disallowed_tool
        |
        v
    ToolExecutionService.execute_tool
        (platform registry + tool:execute + per-tool permissions +
         execution policy + human-approval policy + input schema +
         tenant-scoped audit record)
        |
        success -> record step outcome, continue
        controlled failure -> record safe error_kind, STOP (no later
                              step ever runs after a failure)
        |
        v
    SUCCEEDED (structured SkillExecutionResult)

Security invariants:

- **Single action boundary.** The engine holds NO tool registry and NO
  handlers. It cannot execute anything except by delegating to
  ``ToolExecutionService``, which enforces the platform whitelist,
  centralized RBAC, per-tool required permissions, execution policy,
  human-approval policy, input schemas, and audit recording for every
  call.
- ``Skill.allowed_tools`` is an ADDITIONAL restriction on top of RBAC —
  never a replacement. A caller holding every permission can still be
  denied by the Skill's declared tool set, and vice versa.
- Untrusted proposals only select registered tools. The proposed call
  list may come from a future LLM-driven Agent: LLM output is untrusted
  input, so proposals are validated structurally, matched against
  ``allowed_tools``, resolved through the platform registry, and can
  never name handlers, code, or arbitrary operations.
- Preconditions are deterministic label containment (the existing
  ``SkillService.preconditions_met`` primitive). No expression language,
  no ``eval``/``exec``, no dynamic evaluation of any kind.
- The tenant boundary comes exclusively from the trusted X-10
  ``TenantContext``. Request payloads, tool payloads, and proposed calls
  can never override it, and cross-tenant Skill resolution is impossible
  (the repository is queried with the context tenant only).
- Failures stop the workflow. No automatic retry, no partial-success
  invention: a failed or denied step terminates the execution and is
  reported in the structured result.

Persistence note: durable Skill-execution records are NOT introduced in
this slice (PRD 23 places "Agent Execution" with the future Agent;
TRD 37 leaves the observability implementation open). Tool-level audit
rows ARE persisted for every executed call by ``ToolExecutionService``.
"""

import uuid
from typing import Any, Dict, Iterable, List, Optional

from arc.domain.models import (
    Skill,
    SkillExecutionResult,
    SkillExecutionStatus,
    SkillExecutionStepOutcome,
    SkillStatus,
    TenantContext,
    ToolExecutionStatus,
)
from arc.security.authorization import AuthorizationService
from arc.security.models import AuthenticatedPrincipal
from arc.services.skills import SkillService
from arc.services.tools import (
    ToolDeniedError,
    ToolExecutionError,
    ToolExecutionService,
    ToolNotFoundError,
    ToolValidationError,
)

# Upper bound on proposed tool calls per execution. A Skill execution is
# a bounded, deterministic workflow — not an autonomous planning loop
# (explicitly out of scope until the Agent slice).
MAX_TOOL_CALLS = 10

# Safe, generic error kinds surfaced in structured results. Raw
# exceptions, policies, and internal details never cross this boundary;
# the precise denial reason for calls that reached the tool service is
# observable in the persisted ``tool_execution_records`` audit row.
_ERROR_INACTIVE_SKILL = "inactive_skill"
_ERROR_PRECONDITION_FAILED = "precondition_failed"
_ERROR_APPROVAL_REQUIRED = "approval_required"
_ERROR_DISALLOWED_TOOL = "disallowed_tool"
_ERROR_UNKNOWN_TOOL = "unknown_tool"
_ERROR_TOOL_DENIED = "tool_denied"
_ERROR_INVALID_INPUT = "invalid_input"
_ERROR_EXECUTION_FAILED = "execution_error"


class SkillExecutionService:
    """Controlled Skill execution on top of the existing foundations.

    Composes the existing ``SkillService`` (tenant-scoped resolution and
    the TRD 25 validation primitives) with the existing
    ``ToolExecutionService`` (the platform action boundary). The engine
    adds ONLY orchestration: ordering, gating, and structured outcomes.
    """

    def __init__(self, skill_service: SkillService, tool_service: ToolExecutionService):
        self.skill_service = skill_service
        self.tool_service = tool_service

    async def execute(
        self,
        context: TenantContext,
        principal: AuthenticatedPrincipal,
        skill_id: str,
        tool_calls: List[Dict[str, Any]],
        satisfied_conditions: Iterable[str],
        authorization: AuthorizationService,
    ) -> SkillExecutionResult:
        """Execute a Skill within the trusted tenant.

        Args:
            context: trusted X-10 ``TenantContext``; the sole tenant
                boundary. Caller-supplied tenant identifiers are never
                consulted.
            principal: authenticated principal from the validated JWT;
                attributes every delegated tool call.
            skill_id: identifier of the Skill to resolve within the
                trusted tenant.
            tool_calls: ordered proposed invocations, each
                ``{"tool_name": str, "input": dict}``. Proposals are
                untrusted input (they may originate from LLM output):
                they are validated structurally, checked against
                ``Skill.allowed_tools``, and executed exclusively through
                ``ToolExecutionService``.
            satisfied_conditions: asserted condition labels used for the
                deterministic precondition check.
            authorization: the application ``AuthorizationService``,
                passed through to ``ToolExecutionService`` unchanged so
                per-tool authorization uses the single centralized matrix.

        Returns:
            A structured :class:`SkillExecutionResult`. Controlled
            failures (unmet preconditions, approval-gated Skills,
            disallowed/unknown/denied tools, invalid input, handler
            failure) are returned as terminal statuses — they are valid
            engine outcomes, not exceptions.

        Raises:
            NotFoundError: the Skill does not exist within the trusted
                tenant (cross-tenant Skills are indistinguishable from
                missing ones).
            ValueError: invalid tenant context or malformed request
                metadata (never a controlled outcome).
        """
        if context is None or not context.is_valid:
            raise ValueError("Invalid tenant context")
        self._validate_proposed_calls(tool_calls)
        conditions = self._validated_conditions(satisfied_conditions)

        skill = await self.skill_service.get_skill(context, skill_id)

        if skill.status is not SkillStatus.ACTIVE:
            return self._build_result(
                context,
                skill,
                SkillExecutionStatus.FAILED,
                error_kind=_ERROR_INACTIVE_SKILL,
                steps=[],
            )

        if not self.skill_service.preconditions_met(skill, conditions):
            return self._build_result(
                context,
                skill,
                SkillExecutionStatus.PRECONDITION_FAILED,
                error_kind=_ERROR_PRECONDITION_FAILED,
                steps=[],
            )

        if skill.approval_required:
            # Fail closed before any tool call: the Human Intervention
            # capability is not implemented, so approval requirements can
            # only ever stop an execution (TRD 17.3).
            return self._build_result(
                context,
                skill,
                SkillExecutionStatus.APPROVAL_REQUIRED,
                error_kind=_ERROR_APPROVAL_REQUIRED,
                steps=[],
            )

        completed: List[SkillExecutionStepOutcome] = []
        for sequence, call in enumerate(tool_calls):
            tool_name = call["tool_name"]
            tool_input = call.get("input", {})

            # Gate 1 — the Skill's own declared tool set. This check runs
            # BEFORE the tool service: a proposal outside allowed_tools
            # must never even reach the platform registry.
            if not self.skill_service.is_tool_allowed(skill, tool_name):
                return self._stopped_result(
                    context,
                    skill,
                    SkillExecutionStatus.DENIED,
                    _ERROR_DISALLOWED_TOOL,
                    completed,
                    sequence,
                    tool_name,
                )

            # Gates 2..N — delegated entirely to the single controlled
            # action boundary (registry whitelist, tool:execute, per-tool
            # permissions, policy, schema validation, audit record).
            try:
                executed = await self.tool_service.execute_tool(
                    context, principal, tool_name, tool_input, authorization
                )
            except ToolNotFoundError:
                return self._stopped_result(
                    context,
                    skill,
                    SkillExecutionStatus.FAILED,
                    _ERROR_UNKNOWN_TOOL,
                    completed,
                    sequence,
                    tool_name,
                )
            except ToolDeniedError:
                return self._stopped_result(
                    context,
                    skill,
                    SkillExecutionStatus.FAILED,
                    _ERROR_TOOL_DENIED,
                    completed,
                    sequence,
                    tool_name,
                )
            except ToolValidationError:
                return self._stopped_result(
                    context,
                    skill,
                    SkillExecutionStatus.FAILED,
                    _ERROR_INVALID_INPUT,
                    completed,
                    sequence,
                    tool_name,
                )
            except ToolExecutionError:
                return self._stopped_result(
                    context,
                    skill,
                    SkillExecutionStatus.FAILED,
                    _ERROR_EXECUTION_FAILED,
                    completed,
                    sequence,
                    tool_name,
                )

            completed.append(
                SkillExecutionStepOutcome(
                    sequence=sequence,
                    tool_name=tool_name,
                    status=ToolExecutionStatus.SUCCESS,
                    tool_version=executed.tool_version,
                    output=executed.output,
                )
            )

        return self._build_result(
            context,
            skill,
            SkillExecutionStatus.SUCCEEDED,
            error_kind=None,
            steps=completed,
        )

    # -- internals -----------------------------------------------------

    @staticmethod
    def _validate_proposed_calls(tool_calls: List[Dict[str, Any]]) -> None:
        """Structurally validate proposed tool calls before any execution."""
        if not isinstance(tool_calls, list) or not tool_calls:
            raise ValueError("At least one proposed tool call is required")
        if len(tool_calls) > MAX_TOOL_CALLS:
            raise ValueError(f"A Skill execution accepts at most {MAX_TOOL_CALLS} tool calls")
        for index, call in enumerate(tool_calls):
            if not isinstance(call, dict):
                raise ValueError(f"Tool call {index} must be an object")
            tool_name = call.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name:
                raise ValueError(f"Tool call {index} requires a non-empty tool_name")
            tool_input = call.get("input", {})
            if not isinstance(tool_input, dict):
                raise ValueError(f"Tool call {index} input must be an object")

    @staticmethod
    def _validated_conditions(satisfied_conditions: Iterable[str]) -> List[str]:
        """Validate and materialize the asserted condition labels."""
        if satisfied_conditions is None:
            return []
        conditions = list(satisfied_conditions)
        if not all(isinstance(condition, str) for condition in conditions):
            raise ValueError("Satisfied conditions must be a list of strings")
        return conditions

    def _stopped_result(
        self,
        context: TenantContext,
        skill: Skill,
        status: SkillExecutionStatus,
        error_kind: str,
        completed: List[SkillExecutionStepOutcome],
        failed_sequence: int,
        failed_tool_name: str,
    ) -> SkillExecutionResult:
        """Build the terminal result for an execution stopped at one step.

        Steps before the failure are preserved; the failed step is
        recorded with its safe error kind; steps after it never ran.
        """
        steps = list(completed)
        steps.append(
            SkillExecutionStepOutcome(
                sequence=failed_sequence,
                tool_name=failed_tool_name,
                status=ToolExecutionStatus.FAILED,
                error_kind=error_kind,
            )
        )
        return self._build_result(context, skill, status, error_kind=error_kind, steps=steps)

    @staticmethod
    def _build_result(
        context: TenantContext,
        skill: Skill,
        status: SkillExecutionStatus,
        error_kind: Optional[str],
        steps: List[SkillExecutionStepOutcome],
    ) -> SkillExecutionResult:
        """Assemble the structured execution result.

        ``principal_id`` is the authenticated user carried by the trusted
        context, consistent with the Approved Context Contract and
        ``IntelligenceAnswer`` conventions.
        """
        return SkillExecutionResult(
            id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            principal_id=context.user_id,
            skill_id=skill.id,
            skill_name=skill.name,
            skill_version=skill.version,
            status=status,
            steps=steps,
            error_kind=error_kind,
        )
