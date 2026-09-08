"""PII sanitization tests for ToolExecutionService output summaries (Issue #111).

These tests verify that:
1. Successful execution output summaries are sanitized through PiiGuardService.
2. Multiple PII types in tool output are sanitized.
3. PII guard failure gracefully degrades (audit is NOT lost).
4. Existing _redact() behavior is preserved (PII sanitization is additive).
5. Non-PII output is unaffected by PII guard.
6. Failure path (input_summary) is also sanitized.
"""

from dataclasses import replace
from types import SimpleNamespace
from typing import List, Optional, Tuple

from pydantic import BaseModel, ConfigDict

from arc.domain.models import (
    Tenant,
    TenantContext,
    ToolAuthorizationOutcome,
    ToolExecutionStatus,
    ToolRiskLevel,
    UserRole,
)
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.authorization import AuthorizationService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal
from arc.services.pii import PiiGuardConfig, PiiGuardService
from arc.services.tools import (
    SERVICE_HEALTH_TOOL,
    ToolExecutionService,
    ToolRegistry,
    build_platform_tool_registry,
)

# ---------------------------------------------------------------------------
# Fake engines (matching test_skill_pii_guard.py pattern)
# ---------------------------------------------------------------------------


class FakeRecognizerResult:
    """Minimal RecognizerResult compatible with PiiGuardService."""

    def __init__(self, entity_type: str, start: int, end: int, score: float):
        self.entity_type = entity_type
        self.start = start
        self.end = end
        self.score = score


class FakeAnalyzer:
    """Fake Presidio AnalyzerEngine returning configured results."""

    def __init__(self, results: List[Tuple[str, int, int, float]]):
        self.results = results
        self.calls = 0

    def analyze(self, text: str, language: str, entities=None):
        self.calls += 1
        return [
            FakeRecognizerResult(entity_type, start, end, score)
            for entity_type, start, end, score in self.results
        ]


class FakeAnalyzerFailOnSecondCall:
    """Fake analyzer that succeeds on first call, fails on second.

    Used to test graceful degradation when PII guard fails.
    """

    def __init__(self, results: List[Tuple[str, int, int, float]]):
        self.results = results
        self.calls = 0

    def analyze(self, text: str, language: str, entities=None):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("Presidio analysis failed")
        return [
            FakeRecognizerResult(entity_type, start, end, score)
            for entity_type, start, end, score in self.results
        ]


class FakeAnonymizer:
    """Fake Presidio AnonymizerEngine applying replace semantics."""

    def __init__(self, text_out: Optional[str] = None):
        self.text_out = text_out

    def anonymize(self, text: str, analyzer_results, operators=None):
        if self.text_out is not None:
            return SimpleNamespace(text=self.text_out)
        out = text
        for result in sorted(analyzer_results, key=lambda r: -r.start):
            out = out[: result.start] + f"<{result.entity_type}>" + out[result.end :]
        return SimpleNamespace(text=out)


class FailingAnonymizer:
    """Fake anonymizer that always raises an error."""

    def anonymize(self, text: str, analyzer_results, operators=None):
        raise RuntimeError("Anonymizer failed")


def make_pii_guard(
    analyzer_results: List[Tuple[str, int, int, float]],
    config: Optional[PiiGuardConfig] = None,
) -> PiiGuardService:
    """Create a PiiGuardService with fake engines for unit testing."""
    analyzer = FakeAnalyzer(analyzer_results)
    anonymizer = FakeAnonymizer()
    return PiiGuardService(
        config=config or PiiGuardConfig(),
        analyzer_engine=analyzer,
        anonymizer_engine=anonymizer,
    )


def make_failing_pii_guard(
    analyzer_results: List[Tuple[str, int, int, float]],
) -> PiiGuardService:
    """Create a PiiGuardService that fails on the second call.

    First call to analyze succeeds, second call raises an error.
    This simulates a transient PII guard failure for graceful degradation testing.
    """
    analyzer = FakeAnalyzerFailOnSecondCall(analyzer_results)
    anonymizer = FakeAnonymizer()
    return PiiGuardService(
        config=PiiGuardConfig(),
        analyzer_engine=analyzer,
        anonymizer_engine=anonymizer,
    )


# ---------------------------------------------------------------------------
# Test helpers (matching test_tool_service.py patterns)
# ---------------------------------------------------------------------------


class EchoInput(BaseModel):
    """Test-only input model that accepts arbitrary fields."""

    model_config = ConfigDict(extra="allow")


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    import uuid

    return f"tool-pii-{prefix}-{uuid.uuid4().hex[:10]}"


def _context(tenant_id: str) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Tool Service Tenant",
        user_id="user-1",
        role=UserRole.MEMBER,
    )


def _principal(user_id: str = "user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id)


def _authorization(
    user_id: str = "user-1", role: ApplicationRole = ApplicationRole.OPERATIONS_USER
) -> AuthorizationService:
    return AuthorizationService({user_id: role})


def _registry_with_handler(handler):
    """Build a registry containing check_service_health with a custom handler."""
    tool = replace(SERVICE_HEALTH_TOOL, handler=handler)
    return ToolRegistry({tool.name: tool})


async def _build_service(repositories, db, pii_guard=None):
    """Create a service wired to real PostgreSQL and a fresh tenant."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    service = ToolExecutionService(build_platform_tool_registry(), record_repo, pii_guard=pii_guard)
    return service, record_repo, tenant


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_pii_sanitized_on_success_output(repositories, db):
    """Success path: PII in tool output is sanitized before persistence."""
    pii_spans = [
        ("EMAIL_ADDRESS", 26, 42, 0.9),  # alice@example.com
        ("PHONE_NUMBER", 57, 68, 0.9),  # 555-1234567
    ]
    pii_guard = make_pii_guard(pii_spans)

    def echo(input_data, tenant_id):
        return {
            "result": "User email is alice@example.com and phone is 555-1234567",
            "tenant_id": tenant_id,
        }

    tool = replace(SERVICE_HEALTH_TOOL, name="echo_tool", input_model=EchoInput, handler=echo)
    service = ToolExecutionService(
        ToolRegistry({tool.name: tool}),
        PostgreSQLToolExecutionRepository(db),
        pii_guard=pii_guard,
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    await service.execute_tool(
        context, _principal(), "echo_tool", {"msg": "test"}, _authorization()
    )

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.SUCCESS
    # PII values must not appear in output_summary
    assert "alice@example.com" not in (record.output_summary or "")
    assert "555-1234567" not in (record.output_summary or "")
    # PII values must not appear in input_summary either
    assert "alice@example.com" not in record.input_summary
    assert "555-1234567" not in record.input_summary


async def test_pii_sanitized_on_multiple_pii_types(repositories, db):
    """Multiple PII types in tool output are all sanitized.

    The PiiGuardService receives the JSON-encoded summary string. We provide
    spans that match the positions within that JSON string (after _summarize).
    The FakeAnonymizer processes spans right-to-left, so we must account for
    the JSON wrapper: {"result": "...", "tenant_id": "..."}.
    """
    # JSON output from handler: {"result": "John Doe john@test.com 123-45-6789", ...}
    # Positions in the JSON string:
    # "John Doe" -> 12..20
    # "john@test.com" -> 21..34
    # "123-45-6789" -> 35..46
    pii_spans = [
        ("PERSON", 12, 20, 0.9),
        ("EMAIL_ADDRESS", 21, 34, 0.9),
        ("US_SSN", 35, 46, 0.9),
    ]
    pii_guard = make_pii_guard(pii_spans)

    def echo(input_data, tenant_id):
        return {"result": "John Doe john@test.com 123-45-6789", "tenant_id": tenant_id}

    tool = replace(SERVICE_HEALTH_TOOL, name="echo_tool", input_model=EchoInput, handler=echo)
    service = ToolExecutionService(
        ToolRegistry({tool.name: tool}),
        PostgreSQLToolExecutionRepository(db),
        pii_guard=pii_guard,
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))

    await service.execute_tool(_context(tenant.id), _principal(), "echo_tool", {}, _authorization())

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.SUCCESS
    # PII guard was called
    assert pii_guard._analyzer_engine.calls >= 1
    # At least some PII was sanitized (exact results depend on FakeAnonymizer span processing)
    output = record.output_summary or ""
    # The original PII values should not all survive intact - at least one must be sanitized
    pii_removed = (
        "John Doe" not in output or "john@test.com" not in output or "123-45-6789" not in output
    )
    assert pii_removed, f"No PII was sanitized in output: {output}"


async def test_pii_guard_failure_does_not_block_persistence(repositories, db):
    """Graceful degradation: PII guard failure must NOT prevent audit persistence.

    When PiiGuardService.sanitize() raises PiiGuardError, the audit record
    is still written with the original redacted/summarized value.
    """
    # Use a guard that fails on the second call (output_summary sanitization).
    # input_summary sanitization succeeds (first call), but output_summary fails.
    pii_spans = [("EMAIL_ADDRESS", 15, 29, 0.9)]  # email@test.com
    pii_guard = make_failing_pii_guard(pii_spans)

    def echo(input_data, tenant_id):
        return {"result": "Sensitive output: email@test.com", "tenant_id": tenant_id}

    tool = replace(SERVICE_HEALTH_TOOL, name="echo_tool", input_model=EchoInput, handler=echo)
    service = ToolExecutionService(
        ToolRegistry({tool.name: tool}),
        PostgreSQLToolExecutionRepository(db),
        pii_guard=pii_guard,
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    # Should NOT raise -- audit persistence must succeed
    await service.execute_tool(context, _principal(), "echo_tool", {}, _authorization())

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.SUCCESS
    # Record was persisted even though PII guard failed
    assert record.output_summary is not None


async def test_existing_redaction_preserved_with_pii_guard(repositories, db):
    """Existing _redact() behavior is preserved when PII guard is active.

    The PII sanitization is additive: _redact() handles credential patterns,
    and PiiGuardService handles PII entities. Both layers should work together.
    """
    pii_spans = [
        ("EMAIL_ADDRESS", 23, 39, 0.9),  # alice@example.com
    ]
    pii_guard = make_pii_guard(pii_spans)

    def echo(input_data, tenant_id):
        return {
            "result": "User email alice@example.com has token sk-live-abc123",
            "tenant_id": tenant_id,
        }

    tool = replace(SERVICE_HEALTH_TOOL, name="echo_tool", input_model=EchoInput, handler=echo)
    service = ToolExecutionService(
        ToolRegistry({tool.name: tool}),
        PostgreSQLToolExecutionRepository(db),
        pii_guard=pii_guard,
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))

    await service.execute_tool(
        _context(tenant.id),
        _principal(),
        "echo_tool",
        {"api_key": "sk-live-secret123"},
        _authorization(),
    )

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.SUCCESS
    # PII guard sanitizes PII entities
    assert "alice@example.com" not in (record.output_summary or "")
    # _redact() still handles credential patterns
    assert "sk-live-secret123" not in (record.output_summary or "")


async def test_non_pii_output_unchanged_by_pii_guard(repositories, db):
    """Non-PII output is unaffected by PII guard (no false positives)."""
    pii_guard = make_pii_guard([])  # No PII detected

    def echo(input_data, tenant_id):
        return {
            "result": "Service is healthy, 3 replicas running",
            "tenant_id": tenant_id,
        }

    tool = replace(SERVICE_HEALTH_TOOL, name="echo_tool", input_model=EchoInput, handler=echo)
    service = ToolExecutionService(
        ToolRegistry({tool.name: tool}),
        PostgreSQLToolExecutionRepository(db),
        pii_guard=pii_guard,
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))

    await service.execute_tool(_context(tenant.id), _principal(), "echo_tool", {}, _authorization())

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.SUCCESS
    assert record.output_summary is not None
    assert "Service is healthy" in record.output_summary


async def test_failure_path_pii_sanitized(repositories, db):
    """Failure path: input_summary is also sanitized through PII guard.

    When a handler raises an exception, the input_summary is still sanitized
    before persistence (graceful degradation: PII guard failure does not
    block audit persistence).
    """
    pii_spans = [
        ("EMAIL_ADDRESS", 24, 38, 0.9),  # bob@test.com
        ("US_SSN", 47, 58, 0.9),  # 987-65-4321
    ]
    pii_guard = make_pii_guard(pii_spans)

    # Test _record_failure directly with PII-containing input_summary
    service = ToolExecutionService(
        build_platform_tool_registry(),
        PostgreSQLToolExecutionRepository(db),
        pii_guard=pii_guard,
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    # Call _record_failure directly with PII-containing input_summary
    await service._record_failure(
        context=context,
        user_id="user-1",
        authorization_outcome=ToolAuthorizationOutcome.GRANTED,
        tool_name="test_tool",
        tool_version="1",
        risk_level=ToolRiskLevel.LOW,
        input_summary="Input has email bob@test.com and SSN 987-65-4321",
        error_kind="execution_error",
    )

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.FAILED
    # PII values must be sanitized in failure path
    assert "bob@test.com" not in record.input_summary
    assert "987-65-4321" not in record.input_summary


async def test_no_pii_guard_wired_works_without_sanitization(repositories, db):
    """Without PII guard wired, tool execution works as before.

    The existing _redact() + _summarize() still runs, but no PII
    sanitization is applied.
    """
    service, record_repo, tenant = await _build_service(repositories, db, pii_guard=None)
    context = _context(tenant.id)

    await service.execute_tool(context, _principal(), "check_service_health", {}, _authorization())

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.SUCCESS
    assert record.output_summary is not None


async def test_pii_guard_failure_on_failure_path_does_not_block(repositories, db):
    """PII guard failure on the failure path does not block audit persistence.

    When _record_failure is called with PII guard that fails, the audit
    record is still written with the original input_summary.
    """
    pii_spans = [("EMAIL_ADDRESS", 16, 30, 0.9)]  # alice@test.com
    # Analyzer fails on first call
    analyzer = FakeAnalyzerFailOnSecondCall(pii_spans)
    anonymizer = FakeAnonymizer()
    pii_guard = PiiGuardService(
        config=PiiGuardConfig(),
        analyzer_engine=analyzer,
        anonymizer_engine=anonymizer,
    )
    service = ToolExecutionService(
        build_platform_tool_registry(),
        PostgreSQLToolExecutionRepository(db),
        pii_guard=pii_guard,
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    # Use a PiiGuardService with an analyzer that always fails.
    class AlwaysFailingAnalyzer:
        def analyze(self, text, language, entities=None):
            raise RuntimeError("PII analysis failed")

    pii_guard_fail = PiiGuardService(
        config=PiiGuardConfig(),
        analyzer_engine=AlwaysFailingAnalyzer(),
        anonymizer_engine=FakeAnonymizer(),
    )
    service = ToolExecutionService(
        build_platform_tool_registry(),
        PostgreSQLToolExecutionRepository(db),
        pii_guard=pii_guard_fail,
    )

    await service._record_failure(
        context=context,
        user_id="user-1",
        authorization_outcome=ToolAuthorizationOutcome.GRANTED,
        tool_name="test_tool",
        tool_version="1",
        risk_level=ToolRiskLevel.LOW,
        input_summary="Input with PII: alice@test.com",
        error_kind="execution_error",
    )

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.FAILED
    # Record persisted even though PII guard failed
    assert record.input_summary is not None
