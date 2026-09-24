"""Deterministic fake provider adapters (TRD 33 controlled/fake APIs).

The fake clients return fixed synthetic records so the connector slice is
fully testable and demonstrable without live external accounts. They can
be configured to fail in a controlled way (auth, rate limit, transport,
malformed response) for failure-path tests. They never contain real
credentials or real customer data.
"""

from typing import Optional

from arc.domain.models import ConnectorProvider
from arc.services.connector_providers.base import (
    ProviderAction,
    ProviderActionResult,
    ProviderAuthError,
    ProviderCredential,
    ProviderFetchResult,
    ProviderRateLimitError,
    ProviderRecord,
    ProviderResponseError,
    ProviderTransportError,
    ProviderValidationError,
)
from arc.services.connector_providers.github import validate_github_target
from arc.services.connector_providers.linear import validate_linear_target
from arc.services.connector_providers.slack import (
    SLACK_MAX_MESSAGE_CHARS,
    validate_slack_target,
)

FAILURE_AUTH = "auth"
FAILURE_RATE_LIMIT = "rate_limit"
FAILURE_TRANSPORT = "transport"
FAILURE_MALFORMED = "malformed"


class _FakeAdapter:
    """Shared deterministic behavior for the fake provider adapters."""

    def __init__(self, failure: Optional[str] = None):
        if failure not in (
            None,
            FAILURE_AUTH,
            FAILURE_RATE_LIMIT,
            FAILURE_TRANSPORT,
            FAILURE_MALFORMED,
        ):
            raise ValueError(f"Unknown fake provider failure mode: {failure!r}")
        self._failure = failure

    def _maybe_fail(self) -> None:
        if self._failure == FAILURE_AUTH:
            raise ProviderAuthError("Fake provider rejected the credential")
        if self._failure == FAILURE_RATE_LIMIT:
            raise ProviderRateLimitError("Fake provider rate limit exceeded")
        if self._failure == FAILURE_TRANSPORT:
            raise ProviderTransportError("Fake provider unavailable")
        if self._failure == FAILURE_MALFORMED:
            raise ProviderResponseError("Fake provider returned a malformed response")


class FakeGitHubProvider(_FakeAdapter):
    """Deterministic fake GitHub client (issues for ``owner/repo``)."""

    provider = ConnectorProvider.GITHUB

    async def fetch(
        self,
        credential: ProviderCredential,
        target: str,
        limit: int = 25,
    ) -> ProviderFetchResult:
        validate_github_target(target)
        self._maybe_fail()
        records = [
            ProviderRecord(
                source_id="github-issue-101",
                title="Fix tenant isolation regression",
                content=(
                    "Issue #101: Fix tenant isolation regression\n\n"
                    "Reproduce cross-tenant access on the knowledge search endpoint."
                ),
                url="https://github.com/example/acme/issues/101",
            ),
            ProviderRecord(
                source_id="github-issue-102",
                title="Handle provider rate limits",
                content=(
                    "Issue #102: Handle provider rate limits\n\n"
                    "Return a controlled error and record a failed sync attempt on 429."
                ),
                url="https://github.com/example/acme/issues/102",
            ),
            ProviderRecord(
                source_id="github-issue-103",
                title="Onboard new support engineer",
                content=(
                    "Issue #103: Onboard new support engineer\n\n"
                    "Contact support@example.com for the onboarding checklist."
                ),
                url="https://github.com/example/acme/issues/103",
            ),
        ]
        return ProviderFetchResult(provider=self.provider, records=records[: max(1, int(limit))])


class FakeSlackProvider(_FakeAdapter):
    """Deterministic fake Slack client (messages for a channel)."""

    provider = ConnectorProvider.SLACK

    def __init__(self, failure: Optional[str] = None):
        super().__init__(failure)
        #: Messages this fake would have posted, in order. Test-visible
        #: on purpose: an action tool's whole point is the side effect,
        #: and asserting a returned value alone would not prove one.
        self.posted: list[tuple[str, str]] = []

    async def fetch(
        self,
        credential: ProviderCredential,
        target: str,
        limit: int = 25,
    ) -> ProviderFetchResult:
        validate_slack_target(target)
        self._maybe_fail()
        records = [
            ProviderRecord(
                source_id=f"slack-{target}-1700000001.000001",
                title=f"Slack message in #{target}",
                content=f"Slack message in #{target}:\n\nIncident resolved: API gateway recovered.",
            ),
            ProviderRecord(
                source_id=f"slack-{target}-1700000002.000002",
                title=f"Slack message in #{target}",
                content=(
                    f"Slack message in #{target}:\n\n"
                    "Follow-up: email the on-call rotation at ops@example.com."
                ),
            ),
            ProviderRecord(
                source_id=f"slack-{target}-1700000003.000003",
                title=f"Slack message in #{target}",
                content=f"Slack message in #{target}:\n\nPostmortem link shared for review.",
            ),
        ]
        return ProviderFetchResult(provider=self.provider, records=records[: max(1, int(limit))])

    async def act(
        self,
        credential: ProviderCredential,
        action: ProviderAction,
    ) -> ProviderActionResult:
        """Deterministic fake of ``chat.postMessage`` (ADR-013).

        Applies the SAME validation the live adapter applies before it
        would reach the network, so a test that passes here is testing the
        refusals the live path also makes -- not a permissive stand-in.
        Nothing leaves the process; the posted message is recorded on the
        instance so a test can assert what Arc would have sent.
        """
        validate_slack_target(action.target)
        if len(action.body) > SLACK_MAX_MESSAGE_CHARS:
            raise ProviderValidationError(
                f"Slack message exceeds {SLACK_MAX_MESSAGE_CHARS} characters"
            )
        self._maybe_fail()
        self.posted.append((action.target, action.body))
        return ProviderActionResult(
            provider=self.provider,
            reference=f"1700000100.{len(self.posted):06d}",
            url=None,
        )


class FakeLinearProvider(_FakeAdapter):
    """Deterministic fake Linear client (issues for a team key)."""

    provider = ConnectorProvider.LINEAR

    async def fetch(
        self,
        credential: ProviderCredential,
        target: str,
        limit: int = 25,
    ) -> ProviderFetchResult:
        validate_linear_target(target)
        self._maybe_fail()
        records = [
            ProviderRecord(
                source_id=f"linear-{target.upper()}-101",
                title="Document the connector sync flow",
                content=(
                    f"{target.upper()}-101: Document the connector sync flow\n\n"
                    "Capture the ADR-001 ingestion boundary in the runbook."
                ),
                url="https://linear.app/example/issue/ABC-101",
            ),
            ProviderRecord(
                source_id=f"linear-{target.upper()}-102",
                title="Escalate P2 incident to on-call",
                content=(
                    f"{target.upper()}-102: Escalate P2 incident to on-call\n\n"
                    "Notify the operations channel when the incident exceeds SLA."
                ),
                url="https://linear.app/example/issue/ABC-102",
            ),
        ]
        return ProviderFetchResult(provider=self.provider, records=records[: max(1, int(limit))])
