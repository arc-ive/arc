"""Bounded Agent orchestration above the Skill execution engine (ADR-006).

The Agent is the Unified Intelligence capability that decides WHICH
tenant Skill to run next (PRD 14, TRD 8.3). It sits strictly ABOVE the
existing ``SkillExecutionService`` and adds ONLY orchestration:

    LLM decision (untrusted)
        | strict AgentDecision.parse (fail closed)
        v tenant-scoped Skill catalog containment
        v SkillExecutionService.execute   <- the single action boundary
        v observe structured SkillExecutionResult
        v stop / chain within MAX_AGENT_STEPS

Security invariants:

- **No tool access of any kind.** The Agent holds no ``ToolRegistry``,
  no handlers, and no ``ToolExecutionService`` reference. Every action
  it can ever cause flows through ``SkillExecutionService``, which alone
  enforces ``Skill.allowed_tools``, per-tool RBAC, execution policy,
  input validation, human-approval policy, and tenant-scoped auditing.
- **Untrusted decisions fail closed.** Model output is data, never a
  grant: strict domain parsing rejects any deviation (no coercion), the
  selected ``skill_id`` must exist in the trusted tenant's own catalog,
  and deep request validation stays owned by the execution engine.
- **Tenant boundary comes only from the trusted X-10 context.** The
  model never sees or sets tenant identifiers; the catalog snapshot it
  receives contains no tenant data.
- **Strictly bounded.** At most ``MAX_AGENT_STEPS`` Skill executions per
  run; a provider decline ends the run; every controlled failure stops
  immediately; there are NO retries and NO autonomous looping.
- **Human Intervention is not implemented.** An approval-gated Skill
  stops the run with the propagated ``APPROVAL_REQUIRED`` outcome.
- **Trace persistence is owned by the service layer** (Issue #143).
  Every invocation of ``run()`` attempts to persist an
  ``AgentRunRecord`` from the service, regardless of which
  controller/caller invoked it. Persistence failures are best-effort:
  they never fail the business response.

The default deterministic provider carries no decision script, so the
Agent fails closed (``agent_capability_unavailable``) until a decision
capability is explicitly configured.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from arc.api.correlation import request_id_var
from arc.db.connection import NotFoundError
from arc.domain.models import (
    LLM_CALL_TYPE_PROPOSE_SKILL,
    AgentDecision,
    AgentExecutionResult,
    AgentRunRecord,
    AgentRunRecordStep,
    AgentRunStatus,
    AgentStepOutcome,
    SkillExecutionStatus,
    TenantContext,
)
from arc.security.authorization import AuthorizationService
from arc.security.models import AuthenticatedPrincipal
from arc.services.llm import LlmProvider, SkillSelectingLlm, _current_llm_usage
from arc.services.llm_pricing import build_llm_usage_record
from arc.services.observability import ObservabilityService
from arc.services.skill_execution import SkillExecutionService
from arc.services.skills import SkillService

logger = logging.getLogger(__name__)

# Hard upper bound on Skill executions per Agent run. The Agent is a
# bounded orchestrator, not an autonomous planner (full autonomous loops
# remain out of scope for this slice).
MAX_AGENT_STEPS = 3

# Safe, generic error kinds surfaced in structured results. Raw
# exceptions and internal details never cross this boundary.
_ERROR_CAPABILITY_UNAVAILABLE = "agent_capability_unavailable"
_ERROR_INVALID_DECISION = "invalid_decision"
_ERROR_SKILL_NOT_AVAILABLE = "skill_not_available"
_ERROR_NO_DECISION = "no_decision"
_ERROR_MAX_STEPS_REACHED = "max_steps_reached"


class AgentExecutionService:
    """Bounded Skill orchestration on top of the existing foundations.

    Composes the existing ``SkillService`` (trusted, tenant-scoped
    catalog) with the existing ``SkillExecutionService`` (the single
    action boundary) and an optional decision-capable LLM provider.

    Trace persistence (Issue #143): every invocation of ``run()``
    attempts to persist an ``AgentRunRecord`` via the
    ``observability_service``. Persistence failures are best-effort and
    never fail the business response.
    """

    def __init__(
        self,
        skill_service: SkillService,
        skill_execution_service: SkillExecutionService,
        llm_provider: Optional[LlmProvider] = None,
        observability_service: Optional[ObservabilityService] = None,
        capability_service=None,
    ):
        self.skill_service = skill_service
        self.skill_execution_service = skill_execution_service
        self.llm_provider = llm_provider
        self.observability_service = observability_service
        self.capability_service = capability_service

    async def run(
        self,
        context: TenantContext,
        principal: AuthenticatedPrincipal,
        goal: str,
        authorization: AuthorizationService,
    ) -> AgentExecutionResult:
        """Run one bounded Agent workflow within the trusted tenant.

        Args:
            context: trusted X-10 ``TenantContext``; the sole tenant
                boundary. Model output can never influence it.
            principal: authenticated principal from the validated JWT;
                passed unchanged into every delegated Skill execution.
            goal: free-form description of what the caller wants done.
                Decision input only; never executed directly.
            authorization: the application ``AuthorizationService``,
                passed through unchanged so per-tool authorization uses
                the single centralized matrix.

        Returns:
            A structured :class:`AgentExecutionResult`. Controlled
            failures are valid engine outcomes, not exceptions.

        Raises:
            ValueError: invalid tenant context or empty goal (never a
                controlled outcome).

        Side effects:
            Every terminal outcome (success, failure, approval-required,
            max-steps) is best-effort persisted as an ``AgentRunRecord``
            via the ``observability_service``. Persistence failures are
            logged and never fail the business response.
        """
        if context is None or not context.is_valid:
            raise ValueError("Invalid tenant context")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("Goal cannot be empty")

        # Platform capability gate: agent_execution must be enabled for
        # this tenant. Checked early to fail fast before any DB access.
        if self.capability_service is not None:
            if not await self.capability_service.is_enabled(context.tenant_id, "agent_execution"):
                return self._build_result(
                    context,
                    goal,
                    AgentRunStatus.FAILED,
                    _ERROR_CAPABILITY_UNAVAILABLE,
                    steps=[],
                )

        started_at = datetime.now(timezone.utc)

        if not self._decision_enabled():
            result = self._build_result(
                context,
                goal,
                AgentRunStatus.FAILED,
                _ERROR_CAPABILITY_UNAVAILABLE,
                steps=[],
            )
            await self._persist_trace(result, started_at)
            return result

        # Generate the run ID early so every skill execution record
        # can be linked back to this agent run via agent_run_id.
        run_id = str(uuid.uuid4())

        # Trusted, tenant-scoped catalog. The snapshot given to the model
        # deliberately contains no tenant identifiers.
        catalog = await self.skill_service.list_skills(context)
        catalog_by_id = {skill.id: skill for skill in catalog}
        snapshot = [
            {"id": skill.id, "name": skill.name, "status": skill.status.value} for skill in catalog
        ]

        completed: List[AgentStepOutcome] = []
        for sequence in range(MAX_AGENT_STEPS):
            raw_decision = self.llm_provider.propose_skill(goal, snapshot)
            # run_id, not a second identifier: the usage record has to carry
            # the same id the run is persisted under, or it correlates to
            # nothing.
            await self._record_usage(context, run_id)

            if raw_decision is None:
                # The provider declined to propose a further step: the run
                # ends here. It counts as success only when at least one
                # delegated Skill execution actually succeeded.
                if any(step.status is SkillExecutionStatus.SUCCEEDED for step in completed):
                    result = self._build_result(
                        context,
                        goal,
                        AgentRunStatus.SUCCEEDED,
                        None,
                        completed,
                        run_id=run_id,
                    )
                    await self._persist_trace(result, started_at)
                    return result
                result = self._build_result(
                    context,
                    goal,
                    AgentRunStatus.FAILED,
                    _ERROR_NO_DECISION,
                    completed,
                    run_id=run_id,
                )
                await self._persist_trace(result, started_at)
                return result

            decision = AgentDecision.parse(raw_decision)
            if decision is None:
                # Unusable model output: stop without executing anything.
                result = self._failed_at_decision_boundary(
                    context,
                    goal,
                    completed,
                    _ERROR_INVALID_DECISION,
                    run_id=run_id,
                )
                await self._persist_trace(result, started_at)
                return result
            if decision.skill_id not in catalog_by_id:
                # Outside the trusted tenant's own catalog (unknown,
                # cross-tenant, or deleted): fail closed, execute nothing.
                result = self._failed_at_decision_boundary(
                    context,
                    goal,
                    completed,
                    _ERROR_SKILL_NOT_AVAILABLE,
                    run_id=run_id,
                )
                await self._persist_trace(result, started_at)
                return result

            try:
                executed = await self.skill_execution_service.execute(
                    context,
                    principal,
                    decision.skill_id,
                    decision.tool_calls,
                    decision.satisfied_preconditions,
                    authorization,
                    agent_run_id=run_id,
                )
            except NotFoundError:
                # Deleted between listing and execution: indistinguishable
                # from unavailable, and nothing executed.
                result = self._failed_at_decision_boundary(
                    context,
                    goal,
                    completed,
                    _ERROR_SKILL_NOT_AVAILABLE,
                    run_id=run_id,
                )
                await self._persist_trace(result, started_at)
                return result
            except ValueError:
                # Deep proposal validation is owned by the execution
                # engine; its rejection means the decision was unusable.
                # Nothing executed.
                result = self._failed_at_decision_boundary(
                    context,
                    goal,
                    completed,
                    _ERROR_INVALID_DECISION,
                    run_id=run_id,
                )
                await self._persist_trace(result, started_at)
                return result

            completed.append(
                AgentStepOutcome(
                    sequence=sequence,
                    skill_id=executed.skill_id,
                    skill_name=executed.skill_name,
                    status=executed.status,
                    error_kind=executed.error_kind,
                )
            )

            if executed.status is SkillExecutionStatus.APPROVAL_REQUIRED:
                # Propagate the approval_id from the Skill layer so the
                # caller (API, external orchestrator) can resume after
                # human approval.
                result = self._build_result(
                    context,
                    goal,
                    AgentRunStatus.APPROVAL_REQUIRED,
                    executed.error_kind,
                    completed,
                    run_id=run_id,
                )
                result.approval_id = executed.approval_id
                await self._persist_trace(result, started_at)
                return result
            if executed.status is not SkillExecutionStatus.SUCCEEDED:
                # ANY controlled failure stops the run immediately.
                # There are no retries.
                result = self._build_result(
                    context,
                    goal,
                    AgentRunStatus.FAILED,
                    executed.error_kind,
                    completed,
                    run_id=run_id,
                )
                await self._persist_trace(result, started_at)
                return result

        # The hard bound was reached without the provider ever declining.
        # Fail closed rather than continuing autonomously.
        result = self._build_result(
            context,
            goal,
            AgentRunStatus.MAX_STEPS_REACHED,
            _ERROR_MAX_STEPS_REACHED,
            completed,
            run_id=run_id,
        )
        await self._persist_trace(result, started_at)
        return result

    # -- internals -----------------------------------------------------

    def _decision_enabled(self) -> bool:
        """V1 gate: a decision capability must actually be configured.

        Fails closed when no provider is wired, the wired provider does
        not implement the optional ``SkillSelectingLlm`` capability, or
        the provider declares itself not decision-capable (for example
        the deterministic provider without a decision script): missing
        collaborators can never widen Agent capability.
        """
        return (
            self.llm_provider is not None
            and isinstance(self.llm_provider, SkillSelectingLlm)
            and getattr(self.llm_provider, "skill_decision_capable", True)
        )

    async def _record_usage(self, context, agent_run_id) -> None:
        """Record LLM usage if usage data is available (best effort).

        Reads from the ContextVar set by the provider after each call.
        Deterministic provider with no usage report creates no record.
        Persistence failure is logged and never raised (TRD 24).
        """
        if self.observability_service is None:
            return
        usage = _current_llm_usage.get()
        if usage is None:
            return
        record = build_llm_usage_record(
            usage,
            call_type=LLM_CALL_TYPE_PROPOSE_SKILL,
            tenant_id=context.tenant_id,
            request_id=request_id_var.get(),
            agent_run_id=agent_run_id,
            principal_id=context.user_id,
        )
        await self.observability_service.record_llm_usage(record)

    def _failed_at_decision_boundary(
        self,
        context: TenantContext,
        goal: str,
        completed: List[AgentStepOutcome],
        error_kind: str,
        *,
        run_id: Optional[str] = None,
    ) -> AgentExecutionResult:
        """Terminal result for a run stopped BEFORE executing a Skill.

        Used for unusable decisions and selections outside the trusted
        catalog: no further Skill executes and the executed prefix is
        preserved.
        """
        return self._build_result(
            context,
            goal,
            AgentRunStatus.FAILED,
            error_kind,
            completed,
            run_id=run_id,
        )

    @staticmethod
    def _build_result(
        context: TenantContext,
        goal: str,
        status: AgentRunStatus,
        error_kind: Optional[str],
        steps: List[AgentStepOutcome],
        *,
        run_id: Optional[str] = None,
    ) -> AgentExecutionResult:
        """Assemble the structured run result.

        ``principal_id`` is the authenticated user carried by the trusted
        context, consistent with the other structured results.
        """
        return AgentExecutionResult(
            id=run_id or str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            principal_id=context.user_id,
            goal=goal,
            status=status,
            steps=steps,
            error_kind=error_kind,
        )

    async def _persist_trace(
        self,
        result: AgentExecutionResult,
        started_at: datetime,
    ) -> None:
        """Best-effort trace persistence from the service layer (Issue #143).

        Every terminal outcome of ``run()`` is routed here. The record
        includes ``started_at`` (captured before execution) and
        ``completed_at`` (set to now). Persistence failure is logged and
        never propagated — the business response is always returned.
        """
        if self.observability_service is None:
            return
        try:
            completed_at = datetime.now(timezone.utc)
            trace = AgentRunRecord(
                id=result.id,
                tenant_id=result.tenant_id,
                principal_id=result.principal_id,
                goal=result.goal,
                status=result.status.value,
                error_kind=result.error_kind,
                steps=[
                    AgentRunRecordStep(
                        sequence=step.sequence,
                        skill_id=step.skill_id,
                        skill_name=step.skill_name,
                        status=step.status.value,
                        error_kind=step.error_kind,
                    )
                    for step in result.steps
                ],
                created_at=result.created_at,
                started_at=started_at,
                completed_at=completed_at,
            )
            await self.observability_service.record_agent_run(trace)
        except Exception:
            logger.warning("agent_run_trace_persistence_failed run_id=%s", result.id)
