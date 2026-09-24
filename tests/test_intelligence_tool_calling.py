"""ADR-004 V1 tests: bounded tool calling inside Unified Intelligence.

Security invariants under test:

- The LLM proposal is UNTRUSTED: it is strictly parsed, resolved through
  the platform registry, validated against the tool schema, and executed
  ONLY through the existing ``ToolExecutionService`` choke point.
- The model can never choose a tenant/principal, grant permissions,
  bypass schemas/policies, trigger unknown tools, or cause more than one
  execution per query.
- Missing collaborators (tool service / principal / authorization) fail
  closed to plain reasoning: capability can never widen by accident.
- Auditing continues to flow exclusively through the existing tool
  execution audit mechanism.
"""

from types import SimpleNamespace

import pytest

from arc.domain.models import (
    ApprovedContext,
    ApprovedContextItem,
    KnowledgeSource,
    RetrievalMethod,
    TenantContext,
    ToolProposal,
    UserRole,
)
from arc.security.authorization import AuthorizationService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal
from arc.services.intelligence import UnifiedIntelligenceService
from arc.services.llm import DeterministicLlmProvider, ToolProposingLlm
from arc.services.tools import (
    ToolDeniedError,
    ToolExecutionError,
    ToolExecutionService,
    ToolNotFoundError,
    ToolValidationError,
    build_platform_tool_registry,
)


def _context(tenant_id="tenant-1", user_id="user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Tenant One",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


def _item(content="Approved remote work policy.", sequence=0):
    return ApprovedContextItem(
        document_id="doc-1",
        chunk_id=f"doc-1-c{sequence}",
        content=content,
        source=KnowledgeSource.POLICY,
        provenance="Policy handbook",
        document_version=1,
        sequence=sequence,
        relevance_score=0.9,
        citation_reference=f"doc-1#c{sequence}",
    )


def _approved(items=None):
    from arc.domain.models import ApprovedContextSecurityMetadata

    tenant_id = "tenant-1"
    return ApprovedContext(
        request_id="req-1",
        tenant_id=tenant_id,
        principal_id="user-1",
        query="is the service healthy",
        retrieval_method=RetrievalMethod.DENSE_SEMANTIC,
        items=items if items is not None else [_item()],
        security_metadata=ApprovedContextSecurityMetadata(tenant_id=tenant_id),
    )


def _context_for(approved):
    return TenantContext(
        tenant_id=approved.tenant_id,
        tenant_name="Tenant One",
        user_id=approved.principal_id,
        role=UserRole.MEMBER,
    )


def _admin_authorization() -> AuthorizationService:
    return AuthorizationService({"user-1": ApplicationRole.COMPANY_ADMINISTRATOR})


class FakeRetrieval:
    def __init__(self, approved):
        self.approved = approved

    async def approved_search(self, context, query, limit=5, source_type=None):
        return self.approved


class FakeToolAuditRepository:
    """Captures audit rows exactly like the real repository would."""

    def __init__(self):
        self.records = []

    async def create_record(self, record):
        self.records.append(record)
        return record

    async def create(self, record):
        return await self.create_record(record)


class FakeToolService:
    """Scriptable stand-in for policy/failure boundaries."""

    def __init__(self, result=None, error=None, registry=None):
        self.result = result or {"ok": True}
        self.error = error
        self.calls = []
        # The real service exposes the platform registry, and the
        # intelligence service reads it to tell the model which tools it
        # may propose. A fake that omits it is an incomplete fake, not a
        # reason to make production code defensive.
        self.registry = registry if registry is not None else build_platform_tool_registry()

    async def execute_tool(self, context, principal, tool_name, raw_input, authorization):
        self.calls.append((context.tenant_id, principal.user_id, tool_name, dict(raw_input)))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            tool_name=tool_name,
            tool_version="v1",
            output=self.result,
        )


class CountingLlm(DeterministicLlmProvider):
    """Deterministic provider that counts completion invocations."""

    def __init__(self, script=None):
        super().__init__(tool_proposal_script=script)
        self.completions = 0

    def complete(self, prompt: str) -> str:
        self.completions += 1
        return super().complete(prompt)


def _script(proposal):
    return lambda query: proposal


def _service(retrieval_approved, llm, tool_service):
    return UnifiedIntelligenceService(
        retrieval=FakeRetrieval(retrieval_approved),
        llm_provider=llm,
        tool_service=tool_service,
    )


def _real_tool_service():
    return ToolExecutionService(build_platform_tool_registry(), FakeToolAuditRepository())


# ---------------------------------------------------------------------------
# Proposal contract (strict parsing)
# ---------------------------------------------------------------------------


class TestToolProposalParsing:
    def test_valid_minimal_proposal_parses(self):
        proposal = ToolProposal.parse({"tool_name": "check_service_health", "arguments": {}})
        assert proposal is not None
        assert proposal.tool_name == "check_service_health"
        assert proposal.arguments == {}

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "check_service_health",
            42,
            {},
            {"tool_name": "check_service_health"},
            {"arguments": {}},
            {"tool_name": "x", "arguments": {}, "reason": "injected"},
            {"tool_name": "", "arguments": {}},
            {"tool_name": "   ", "arguments": {}},
            {"tool_name": "x" * 256, "arguments": {}},
            {"tool_name": 7, "arguments": {}},
            {"tool_name": "check_service_health", "arguments": [1, 2]},
            {"tool_name": "check_service_health", "arguments": {1: "v"}},
        ],
    )
    def test_malformed_outputs_fail_closed_to_no_proposal(self, raw):
        assert ToolProposal.parse(raw) is None


class TestProposerCapabilityGate:
    def test_unarmed_provider_never_proposes(self):
        provider = DeterministicLlmProvider()
        assert isinstance(provider, ToolProposingLlm)
        assert provider.propose_tool("anything") is None


# ---------------------------------------------------------------------------
# Intelligence integration (fake boundaries)
# ---------------------------------------------------------------------------


class TestIntelligenceToolCallingFlow:
    def _approved(self):
        return _approved()

    async def test_no_script_means_plain_reasoning_and_zero_executions(self):
        approved = self._approved()
        llm = CountingLlm(script=None)
        tool_service = FakeToolService()
        service = _service(approved, llm, tool_service)

        answer = await service.answer_query(_context_for(approved), "any query")

        assert llm.propose_tool("any query") is None
        assert tool_service.calls == []
        assert answer.tool_executions == []
        assert llm.completions == 1

    async def test_valid_proposal_executes_exactly_once_and_answer_references_it(self):
        approved = self._approved()
        llm = CountingLlm(script=_script({"tool_name": "check_service_health", "arguments": {}}))
        tool_service = FakeToolService(result={"services": [{"name": "api", "status": "healthy"}]})
        service = _service(approved, llm, tool_service)

        answer = await service.answer_query(
            _context_for(approved),
            "health?",
            principal=_principal(),
            authorization=_admin_authorization(),
        )

        assert len(tool_service.calls) == 1
        assert answer.tool_executions == [
            {"tool_name": "check_service_health", "tool_version": "v1"}
        ]
        # Single iteration: exactly ONE reasoning completion for the whole
        # propose→execute→observe→answer cycle.
        assert llm.completions == 1
        assert "TOOL OBSERVATION" in prompt_of_last(llm)

    async def test_unknown_tool_yields_controlled_unknown_observation_without_execution(self):
        approved = self._approved()
        llm = CountingLlm(script=_script({"tool_name": "delete_everything", "arguments": {}}))
        tool_service = FakeToolService(error=ToolNotFoundError("delete_everything"))
        service = _service(approved, llm, tool_service)

        answer = await service.answer_query(
            _context_for(approved),
            "q",
            principal=_principal(),
            authorization=_admin_authorization(),
        )

        assert len(tool_service.calls) == 1  # attempted resolution only
        assert answer.tool_executions == []
        assert '"status": "unknown_tool"' in prompt_of_last(llm)

    async def test_invalid_arguments_yield_controlled_observation(self):
        approved = self._approved()
        llm = CountingLlm(script=_script({"tool_name": "t", "arguments": {"a": 1}}))
        tool_service = FakeToolService(error=ToolValidationError("bad input"))
        service = _service(approved, llm, tool_service)

        answer = await service.answer_query(
            _context_for(approved),
            "q",
            principal=_principal(),
            authorization=_admin_authorization(),
        )

        assert answer.tool_executions == []
        assert '"status": "invalid_arguments"' in prompt_of_last(llm)

    async def test_denied_authorization_yields_controlled_denied_observation(self):
        approved = self._approved()
        llm = CountingLlm(script=_script({"tool_name": "t", "arguments": {}}))
        tool_service = FakeToolService(error=ToolDeniedError("denied"))
        service = _service(approved, llm, tool_service)

        answer = await service.answer_query(
            _context_for(approved),
            "q",
            principal=_principal(),
            authorization=_admin_authorization(),
        )

        assert answer.tool_executions == []
        assert '"status": "authorization_or_policy_denied"' in prompt_of_last(llm)

    async def test_require_human_approval_style_denial_fails_closed(self):
        approved = self._approved()
        llm = CountingLlm(script=_script({"tool_name": "restart_service", "arguments": {}}))
        # REQUIRE_HUMAN_APPROVAL surfaces as a denial while no approval gate exists.
        tool_service = FakeToolService(error=ToolDeniedError("human approval required"))
        service = _service(approved, llm, tool_service)

        answer = await service.answer_query(
            _context_for(approved),
            "q",
            principal=_principal(),
            authorization=_admin_authorization(),
        )

        assert answer.tool_executions == []  # never executed
        assert '"status": "authorization_or_policy_denied"' in prompt_of_last(llm)

    async def test_execution_failure_yields_failed_observation(self):
        approved = self._approved()
        llm = CountingLlm(script=_script({"tool_name": "t", "arguments": {}}))
        tool_service = FakeToolService(error=ToolExecutionError("handler exploded"))
        service = _service(approved, llm, tool_service)

        answer = await service.answer_query(
            _context_for(approved),
            "q",
            principal=_principal(),
            authorization=_admin_authorization(),
        )

        assert answer.tool_executions == []
        assert '"status": "execution_failed"' in prompt_of_last(llm)

    async def test_missing_principal_fails_closed_to_plain_reasoning(self):
        approved = self._approved()
        llm = CountingLlm(script=_script({"tool_name": "check_service_health", "arguments": {}}))
        tool_service = FakeToolService()
        service = _service(approved, llm, tool_service)

        answer = await service.answer_query(_context_for(approved), "q", principal=None)

        assert tool_service.calls == []  # capability must NOT widen
        assert answer.tool_executions == []
        assert llm.completions == 1

    async def test_missing_authorization_fails_closed_to_plain_reasoning(self):
        approved = self._approved()
        llm = CountingLlm(script=_script({"tool_name": "check_service_health", "arguments": {}}))
        tool_service = FakeToolService()
        service = _service(approved, llm, tool_service)

        answer = await service.answer_query(
            _context_for(approved), "q", principal=_principal(), authorization=None
        )

        assert tool_service.calls == []
        assert answer.tool_executions == []


class TestSingleIterationAndNoLoops:
    async def test_one_proposal_causes_at_most_one_execution_and_one_completion(self):
        approved = _approved()
        llm = CountingLlm(script=_script({"tool_name": "check_service_health", "arguments": {}}))
        tool_service = FakeToolService()
        service = _service(approved, llm, tool_service)

        await service.answer_query(
            _context_for(approved),
            "health?",
            principal=_principal(),
            authorization=_admin_authorization(),
        )

        assert len(tool_service.calls) == 1
        assert llm.completions == 1


def prompt_of_last(llm: CountingLlm) -> str:
    """Return the last prompt seen by the counting provider."""
    return llm.last_prompt


# Patch CountingLlm to remember prompts (kept after class for readability).
_original_complete = CountingLlm.complete


def _counting_complete(self, prompt: str) -> str:
    self.last_prompt = prompt
    return _original_complete(self, prompt)


CountingLlm.complete = _counting_complete
CountingLlm.last_prompt = ""


def _principal(user_id="user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id)


# ---------------------------------------------------------------------------
# Real ToolExecutionService integration (registry/schema/authz/audit)
# ---------------------------------------------------------------------------


class TestRealToolExecutionBoundary:
    def _company_admin_service(self):
        return AuthorizationService({"user-1": ApplicationRole.COMPANY_ADMINISTRATOR})

    def _employee_authorization(self):
        return AuthorizationService({"user-1": ApplicationRole.EMPLOYEE})

    async def test_valid_proposal_executes_through_real_service_and_audits(self):
        approved = _approved()
        audit_repo = FakeToolAuditRepository()
        tool_service = ToolExecutionService(build_platform_tool_registry(), audit_repo)
        llm = CountingLlm(script=_script({"tool_name": "check_service_health", "arguments": {}}))
        service = UnifiedIntelligenceService(
            retrieval=FakeRetrieval(approved),
            llm_provider=llm,
            tool_service=tool_service,
        )
        context = _context_for(approved)
        principal = AuthenticatedPrincipal(user_id=context.user_id)
        authorization = self._company_admin_service()

        answer = await service.answer_query(
            _context_for(approved),
            "health?",
            principal=principal,
            authorization=authorization,
        )

        assert len(answer.tool_executions) == 1
        assert answer.tool_executions[0]["tool_name"] == "check_service_health"
        assert len(audit_repo.records) == 1
        record = audit_repo.records[0]
        assert record.status.value == "success"
        assert record.tenant_id == context.tenant_id

    async def test_unauthorized_role_is_denied_and_audited_without_execution(self):
        approved = _approved()
        audit_repo = FakeToolAuditRepository()
        tool_service = ToolExecutionService(build_platform_tool_registry(), audit_repo)
        llm = CountingLlm(script=_script({"tool_name": "check_service_health", "arguments": {}}))
        service = UnifiedIntelligenceService(
            retrieval=FakeRetrieval(approved),
            llm_provider=llm,
            tool_service=tool_service,
        )
        context = _context_for(approved)
        principal = AuthenticatedPrincipal(user_id=context.user_id)

        answer = await service.answer_query(
            _context_for(approved),
            "health?",
            principal=principal,
            authorization=self._employee_authorization(),
        )

        assert answer.tool_executions == []
        assert len(audit_repo.records) == 1
        assert audit_repo.records[0].status.value == "failed"
        assert audit_repo.records[0].authorization_outcome.value == "denied"

    async def test_model_supplied_tenant_argument_is_inert_and_rejected_by_schema(self):
        approved = _approved()
        audit_repo = FakeToolAuditRepository()
        tool_service = ToolExecutionService(build_platform_tool_registry(), audit_repo)
        llm = CountingLlm(
            script=_script(
                {
                    "tool_name": "check_service_health",
                    "arguments": {"tenant_id": "tenant-B"},
                }
            )
        )
        service = UnifiedIntelligenceService(
            retrieval=FakeRetrieval(approved),
            llm_provider=llm,
            tool_service=tool_service,
        )
        context = _context_for(approved)
        principal = AuthenticatedPrincipal(user_id=context.user_id)
        authorization = self._company_admin_service()

        answer = await service.answer_query(
            context,
            "health?",
            principal=principal,
            authorization=authorization,
        )

        # extra="forbid" on the tool schema rejects the injected argument;
        # nothing executes and the trusted tenant is unaffected.
        assert answer.tool_executions == []
        assert len(audit_repo.records) == 1
        assert audit_repo.records[0].tenant_id == context.tenant_id
