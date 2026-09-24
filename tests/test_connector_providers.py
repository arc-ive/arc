"""Tests for connector provider adapters, settings, and registry.

Security invariants under test:

- Credentials are never exposed through any representation: ``repr``
  masks the token and no adapter error contains credential material.
- Configuration fails closed: invalid JSON, unknown providers, empty
  tokens, and unknown provider modes raise ``ConnectorConfigurationError``.
- Adapters validate the tenant-supplied target BEFORE any request is
  made; tenant input never selects a network destination.
- Provider responses are validated into typed records; unexpected shapes
  fail closed with controlled errors (auth/rate limit/transport/response).
- The registry is code-defined and read-only: only the approved providers
  (GitHub, Slack, Linear per ADR-002) are ever available.
"""

import json
import uuid

import httpx
import pytest

from arc.domain.models import ConnectorProvider
from arc.services.connector_providers.base import (
    ProviderAction,
    ProviderAuthError,
    ProviderCredential,
    ProviderRateLimitError,
    ProviderRecord,
    ProviderResponseError,
    ProviderTransportError,
    ProviderValidationError,
)
from arc.services.connector_providers.fake import (
    FAILURE_AUTH,
    FAILURE_MALFORMED,
    FAILURE_RATE_LIMIT,
    FAILURE_TRANSPORT,
    FakeGitHubProvider,
    FakeLinearProvider,
    FakeSlackProvider,
)
from arc.services.connector_providers.github import GitHubProviderAdapter
from arc.services.connector_providers.linear import LinearProviderAdapter
from arc.services.connector_providers.registry import ProviderRegistry, build_provider_registry
from arc.services.connector_providers.settings import (
    ConnectorConfigurationError,
    ConnectorCredentialStore,
    ConnectorSettings,
    _parse_connector_credentials,
    get_connector_settings,
)
from arc.services.connector_providers.slack import (
    SLACK_CHAT_POST_MESSAGE_URL,
    SLACK_MAX_MESSAGE_CHARS,
    SlackProviderAdapter,
)
from arc.services.connector_providers.targets import assert_approved_provider_url

ALL_PROVIDERS = {
    ConnectorProvider.GITHUB,
    ConnectorProvider.SLACK,
    ConnectorProvider.LINEAR,
}


def _unique(prefix: str) -> str:
    return f"cp-{prefix}-{uuid.uuid4().hex[:10]}"


class TestProviderCredential:
    def test_repr_never_exposes_token(self):
        credential = ProviderCredential(
            provider=ConnectorProvider.GITHUB, token="super-secret-token"
        )
        assert "super-secret-token" not in repr(credential)
        assert "***" in repr(credential)

    def test_empty_token_is_rejected(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            ProviderCredential(provider=ConnectorProvider.GITHUB, token="")

    def test_invalid_provider_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid connector provider"):
            ProviderCredential(provider="github", token="token")


class TestProviderRecordValidation:
    def test_empty_source_id_is_rejected(self):
        with pytest.raises(ValueError, match="source_id"):
            ProviderRecord(source_id="", title="t", content="c")

    def test_empty_title_is_rejected(self):
        with pytest.raises(ValueError, match="title"):
            ProviderRecord(source_id="s", title="", content="c")

    def test_empty_content_is_rejected(self):
        with pytest.raises(ValueError, match="content"):
            ProviderRecord(source_id="s", title="t", content="")


class TestConnectorSettings:
    def test_default_mode_is_simulated(self, monkeypatch):
        monkeypatch.delenv("CONNECTOR_PROVIDER_MODE", raising=False)
        settings = get_connector_settings()
        assert settings.provider_mode == "simulated"

    def test_live_mode_is_accepted(self):
        assert ConnectorSettings(provider_mode="live").provider_mode == "live"

    def test_unknown_mode_fails_closed(self):
        with pytest.raises(ConnectorConfigurationError, match="CONNECTOR_PROVIDER_MODE"):
            ConnectorSettings(provider_mode="production")


class TestCredentialParsing:
    def test_empty_credentials_parse_to_empty(self):
        assert _parse_connector_credentials("") == {}

    def test_valid_credentials_parse(self):
        raw = json.dumps({"tenant-a": {"github": "gh-token", "linear": "ln-token"}})
        parsed = _parse_connector_credentials(raw)
        assert parsed["tenant-a"][ConnectorProvider.GITHUB] == "gh-token"
        assert parsed["tenant-a"][ConnectorProvider.LINEAR] == "ln-token"

    def test_invalid_json_fails_closed(self):
        with pytest.raises(ConnectorConfigurationError, match="valid JSON"):
            _parse_connector_credentials("{not json")

    def test_non_object_root_fails_closed(self):
        with pytest.raises(ConnectorConfigurationError, match="JSON object"):
            _parse_connector_credentials("[1, 2]")

    def test_unknown_provider_fails_closed(self):
        raw = json.dumps({"tenant-a": {"dropbox": "token"}})
        with pytest.raises(ConnectorConfigurationError, match="Unknown connector provider"):
            _parse_connector_credentials(raw)

    def test_empty_token_fails_closed(self):
        raw = json.dumps({"tenant-a": {"github": ""}})
        with pytest.raises(ConnectorConfigurationError, match="non-empty string"):
            _parse_connector_credentials(raw)

    def test_non_object_provider_map_fails_closed(self):
        raw = json.dumps({"tenant-a": "github-token"})
        with pytest.raises(ConnectorConfigurationError, match="must be a JSON object"):
            _parse_connector_credentials(raw)


class TestConnectorCredentialStore:
    def test_lazy_env_read(self, monkeypatch):
        monkeypatch.setenv(
            "CONNECTOR_CREDENTIALS",
            json.dumps({"tenant-a": {"github": "env-token"}}),
        )
        store = ConnectorCredentialStore()
        assert store.get("tenant-a", ConnectorProvider.GITHUB) == "env-token"

    def test_missing_tenant_returns_none(self, monkeypatch):
        monkeypatch.setenv("CONNECTOR_CREDENTIALS", json.dumps({"tenant-a": {"github": "t"}}))
        store = ConnectorCredentialStore()
        assert store.get("tenant-b", ConnectorProvider.GITHUB) is None

    def test_missing_provider_returns_none(self, monkeypatch):
        monkeypatch.setenv("CONNECTOR_CREDENTIALS", json.dumps({"tenant-a": {"github": "t"}}))
        store = ConnectorCredentialStore()
        assert store.get("tenant-a", ConnectorProvider.SLACK) is None

    def test_missing_env_returns_none(self, monkeypatch):
        monkeypatch.delenv("CONNECTOR_CREDENTIALS", raising=False)
        assert ConnectorCredentialStore().get("tenant-a", ConnectorProvider.GITHUB) is None


class TestFakeProviders:
    @pytest.mark.parametrize(
        "adapter, target",
        [
            (FakeGitHubProvider(), "example/acme"),
            (FakeSlackProvider(), "general"),
            (FakeLinearProvider(), "abc"),
        ],
    )
    async def test_fake_fetch_returns_valid_records(self, adapter, target):
        credential = ProviderCredential(provider=adapter.provider, token="dev-token")
        result = await adapter.fetch(credential, target)
        assert result.provider == adapter.provider
        assert isinstance(result.records, list)
        assert result.records
        for record in result.records:
            assert record.source_id
            assert record.title
            assert record.content
            assert "dev-token" not in record.content

    @pytest.mark.parametrize(
        "adapter, bad_target",
        [
            (FakeGitHubProvider(), "no-slash"),
            (FakeSlackProvider(), "UPPER"),
            (FakeLinearProvider(), "bad target with spaces"),
        ],
    )
    async def test_fake_rejects_invalid_targets(self, adapter, bad_target):
        credential = ProviderCredential(provider=adapter.provider, token="dev-token")
        with pytest.raises(ProviderValidationError):
            await adapter.fetch(credential, bad_target)

    @pytest.mark.parametrize(
        "failure, error_type",
        [
            (FAILURE_AUTH, ProviderAuthError),
            (FAILURE_RATE_LIMIT, ProviderRateLimitError),
            (FAILURE_TRANSPORT, ProviderTransportError),
            (FAILURE_MALFORMED, ProviderResponseError),
        ],
    )
    async def test_fake_failure_injection(self, failure, error_type):
        adapter = FakeGitHubProvider(failure=failure)
        credential = ProviderCredential(provider=ConnectorProvider.GITHUB, token="dev-token")
        with pytest.raises(error_type):
            await adapter.fetch(credential, "example/acme")

    def test_unknown_failure_mode_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown fake provider failure mode"):
            FakeGitHubProvider(failure="explode")


class TestRegistry:
    def test_simulated_registry_has_only_approved_providers(self):
        registry = build_provider_registry(ConnectorSettings(provider_mode="simulated"))
        assert registry.providers() == ALL_PROVIDERS

    def test_live_registry_has_only_approved_providers(self):
        registry = build_provider_registry(ConnectorSettings(provider_mode="live"))
        assert registry.providers() == ALL_PROVIDERS

    def test_registry_get_returns_adapter(self):
        registry = build_provider_registry(ConnectorSettings(provider_mode="simulated"))
        adapter = registry.get(ConnectorProvider.GITHUB)
        assert isinstance(adapter, FakeGitHubProvider)

    def test_registry_get_unknown_provider_returns_none(self):
        registry = ProviderRegistry()
        assert registry.get(ConnectorProvider.GITHUB) is None


class TestGitHubAdapter:
    def _adapter(self, handler):
        transport = httpx.MockTransport(handler)
        return GitHubProviderAdapter(client=httpx.AsyncClient(transport=transport))

    async def test_github_valid_response_parses_issues(self):
        def handler(request):
            assert request.url.path == "/repos/example/acme/issues"
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 42,
                        "title": "Fix bug",
                        "body": "Details here",
                        "html_url": "https://github.com/example/acme/issues/42",
                    }
                ],
            )

        adapter = self._adapter(handler)
        result = await adapter.fetch(
            ProviderCredential(provider=ConnectorProvider.GITHUB, token="dev-token"),
            "example/acme",
        )
        assert len(result.records) == 1
        assert result.records[0].source_id == "github-issue-42"
        assert result.records[0].title == "Fix bug"
        assert "Details here" in result.records[0].content

    async def test_github_401_maps_to_auth_error(self):
        def handler(request):
            return httpx.Response(401, json={"message": "Bad credentials"})

        with pytest.raises(ProviderAuthError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="bad"),
                "example/acme",
            )

    async def test_github_429_maps_to_rate_limit(self):
        def handler(request):
            return httpx.Response(429, json={"message": "rate limit"})

        with pytest.raises(ProviderRateLimitError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="t"),
                "example/acme",
            )

    async def test_github_500_maps_to_transport_error(self):
        def handler(request):
            return httpx.Response(500, json={})

        with pytest.raises(ProviderTransportError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="t"),
                "example/acme",
            )

    async def test_github_malformed_payload_fails_closed(self):
        def handler(request):
            return httpx.Response(200, json={"not": "a list"})

        with pytest.raises(ProviderResponseError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="t"),
                "example/acme",
            )

    async def test_github_invalid_target_rejected_before_request(self):
        called = False

        def handler(request):
            nonlocal called
            called = True
            return httpx.Response(200, json=[])

        with pytest.raises(ProviderValidationError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="t"),
                "not-a-valid/target/with/extra",
            )
        assert not called

    async def test_github_network_failure_maps_to_transport_error(self):
        def handler(request):
            raise httpx.ConnectError("no route")

        with pytest.raises(ProviderTransportError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="t"),
                "example/acme",
            )


class TestSlackAdapter:
    def _adapter(self, handler):
        transport = httpx.MockTransport(handler)
        return SlackProviderAdapter(client=httpx.AsyncClient(transport=transport))

    async def test_slack_resolves_channel_and_parses_messages(self):
        def handler(request):
            if request.url.path == "/api/conversations.list":
                return httpx.Response(
                    200,
                    json={"ok": True, "channels": [{"id": "C123", "name": "general"}]},
                )
            assert request.url.path == "/api/conversations.history"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "messages": [{"text": "Release notes", "ts": "1700000001.000001"}],
                },
            )

        result = await self._adapter(handler).fetch(
            ProviderCredential(provider=ConnectorProvider.SLACK, token="dev-token"),
            "general",
        )
        assert len(result.records) == 1
        assert result.records[0].source_id == "slack-general-1700000001.000001"
        assert "Release notes" in result.records[0].content

    async def test_slack_channel_not_found_raises_validation_error(self):
        def handler(request):
            return httpx.Response(
                200,
                json={"ok": True, "channels": [{"id": "C1", "name": "other"}]},
            )

        with pytest.raises(ProviderValidationError, match="was not found"):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.SLACK, token="t"),
                "missing-channel",
            )

    async def test_slack_ok_false_auth_error(self):
        def handler(request):
            return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

        with pytest.raises(ProviderAuthError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.SLACK, token="bad"),
                "general",
            )

    async def test_slack_ratelimited_envelope(self):
        def handler(request):
            return httpx.Response(200, json={"ok": False, "error": "ratelimited"})

        with pytest.raises(ProviderRateLimitError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.SLACK, token="t"),
                "general",
            )

    async def test_slack_non_object_response_fails_closed(self):
        def handler(request):
            return httpx.Response(200, json=[1, 2, 3])

        with pytest.raises(ProviderResponseError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.SLACK, token="t"),
                "general",
            )

    async def test_slack_invalid_target_rejected(self):
        with pytest.raises(ProviderValidationError):
            await self._adapter(lambda r: httpx.Response(200, json={})).fetch(
                ProviderCredential(provider=ConnectorProvider.SLACK, token="t"),
                "Bad Channel",
            )


class TestSlackActAdapter:
    """The write side of the Slack adapter (ADR-013).

    ``fetch`` is covered above; these cover ``act``, which is the first
    adapter method whose success means something happened outside Arc.
    """

    def _adapter(self, handler):
        transport = httpx.MockTransport(handler)
        return SlackProviderAdapter(client=httpx.AsyncClient(transport=transport))

    def _credential(self):
        return ProviderCredential(provider=ConnectorProvider.SLACK, token="xoxb-act")

    async def test_posts_to_the_resolved_channel_id(self):
        """The channel is resolved by NAME; no ID or URL comes from input."""
        seen = {}

        def handler(request):
            if request.url.path == "/api/conversations.list":
                return httpx.Response(
                    200, json={"ok": True, "channels": [{"id": "C999", "name": "ops"}]}
                )
            assert request.url.path == "/api/chat.postMessage"
            assert request.method == "POST"
            seen["body"] = json.loads(request.content)
            seen["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"ok": True, "ts": "1700000009.000009"})

        result = await self._adapter(handler).act(
            self._credential(), ProviderAction(target="ops", body="Deploy finished")
        )

        assert result.reference == "1700000009.000009"
        assert seen["body"] == {"channel": "C999", "text": "Deploy finished"}
        assert seen["auth"] == "Bearer xoxb-act"

    async def test_an_invalid_channel_name_makes_no_request(self):
        """Validation happens before the network, not after."""
        calls = []

        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={"ok": True})

        with pytest.raises(ProviderValidationError):
            await self._adapter(handler).act(
                self._credential(), ProviderAction(target="Bad Channel", body="hello")
            )
        assert calls == []

    async def test_an_over_long_message_makes_no_request(self):
        """Refused rather than silently truncated or split by Slack."""
        calls = []

        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={"ok": True})

        with pytest.raises(ProviderValidationError, match="characters"):
            await self._adapter(handler).act(
                self._credential(),
                ProviderAction(target="ops", body="x" * (SLACK_MAX_MESSAGE_CHARS + 1)),
            )
        assert calls == []

    async def test_an_unknown_channel_is_refused_before_posting(self):
        posted = []

        def handler(request):
            if request.url.path == "/api/conversations.list":
                return httpx.Response(
                    200, json={"ok": True, "channels": [{"id": "C1", "name": "other"}]}
                )
            posted.append(request.url.path)
            return httpx.Response(200, json={"ok": True, "ts": "1.1"})

        with pytest.raises(ProviderValidationError, match="was not found"):
            await self._adapter(handler).act(
                self._credential(), ProviderAction(target="ops", body="hello")
            )
        assert posted == []

    async def test_a_rejected_token_raises_an_auth_error(self):
        """The act token can be wrong even when the read token is right."""

        def handler(request):
            if request.url.path == "/api/conversations.list":
                return httpx.Response(
                    200, json={"ok": True, "channels": [{"id": "C1", "name": "ops"}]}
                )
            return httpx.Response(200, json={"ok": False, "error": "not_authed"})

        with pytest.raises(ProviderAuthError):
            await self._adapter(handler).act(
                self._credential(), ProviderAction(target="ops", body="hello")
            )

    async def test_a_missing_scope_error_is_not_reported_as_success(self):
        """``chat:write`` absent is the most likely real-world failure."""

        def handler(request):
            if request.url.path == "/api/conversations.list":
                return httpx.Response(
                    200, json={"ok": True, "channels": [{"id": "C1", "name": "ops"}]}
                )
            return httpx.Response(200, json={"ok": False, "error": "missing_scope"})

        with pytest.raises(ProviderResponseError, match="missing_scope"):
            await self._adapter(handler).act(
                self._credential(), ProviderAction(target="ops", body="hello")
            )

    async def test_a_response_without_a_timestamp_fails_closed(self):
        """No reference means Arc cannot evidence what it created."""

        def handler(request):
            if request.url.path == "/api/conversations.list":
                return httpx.Response(
                    200, json={"ok": True, "channels": [{"id": "C1", "name": "ops"}]}
                )
            return httpx.Response(200, json={"ok": True})

        with pytest.raises(ProviderResponseError, match="timestamp"):
            await self._adapter(handler).act(
                self._credential(), ProviderAction(target="ops", body="hello")
            )

    async def test_the_post_endpoint_is_on_the_provider_allowlist(self):
        """Defense in depth: the URL is checked even though it is a constant."""
        assert_approved_provider_url(ConnectorProvider.SLACK, SLACK_CHAT_POST_MESSAGE_URL)


class TestLinearAdapter:
    def _adapter(self, handler):
        transport = httpx.MockTransport(handler)
        return LinearProviderAdapter(client=httpx.AsyncClient(transport=transport))

    async def test_linear_valid_response_parses_issues(self):
        def handler(request):
            assert request.url.path == "/graphql"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "team": {
                            "issues": {
                                "nodes": [
                                    {
                                        "identifier": "ABC-1",
                                        "title": "Fix bug",
                                        "description": "Details",
                                        "url": "https://linear.app/x/issue/ABC-1",
                                    }
                                ]
                            }
                        }
                    }
                },
            )

        result = await self._adapter(handler).fetch(
            ProviderCredential(provider=ConnectorProvider.LINEAR, token="dev-token"),
            "abc",
        )
        assert len(result.records) == 1
        assert result.records[0].source_id == "linear-ABC-1"
        assert result.records[0].title == "Fix bug"
        assert "Details" in result.records[0].content

    async def test_linear_graphql_errors_fail_closed(self):
        def handler(request):
            return httpx.Response(200, json={"errors": [{"message": "team not found"}]})

        with pytest.raises(ProviderResponseError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.LINEAR, token="t"),
                "abc",
            )

    async def test_linear_missing_team_fails_closed(self):
        def handler(request):
            return httpx.Response(200, json={"data": {"team": None}})

        with pytest.raises(ProviderResponseError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.LINEAR, token="t"),
                "abc",
            )

    async def test_linear_401_maps_to_auth_error(self):
        def handler(request):
            return httpx.Response(401, json={})

        with pytest.raises(ProviderAuthError):
            await self._adapter(handler).fetch(
                ProviderCredential(provider=ConnectorProvider.LINEAR, token="bad"),
                "abc",
            )

    async def test_linear_invalid_target_rejected(self):
        with pytest.raises(ProviderValidationError):
            await self._adapter(lambda r: httpx.Response(200, json={})).fetch(
                ProviderCredential(provider=ConnectorProvider.LINEAR, token="t"),
                "bad target",
            )


class TestProviderTargetAllowlist:
    """Strict SSRF protection: only approved provider endpoints may be
    requested, before any external request is made."""

    @pytest.mark.parametrize(
        "provider,url",
        [
            (ConnectorProvider.GITHUB, "https://api.github.com/repos/a/b/issues"),
            (ConnectorProvider.SLACK, "https://slack.com/api/conversations.list"),
            (ConnectorProvider.LINEAR, "https://api.linear.app/graphql"),
        ],
    )
    def test_approved_provider_urls_are_allowed(self, provider, url):
        assert assert_approved_provider_url(provider, url) == url

    @pytest.mark.parametrize(
        "provider,url",
        [
            (ConnectorProvider.GITHUB, "http://api.github.com/repos/a/b/issues"),
            (ConnectorProvider.GITHUB, "https://api.github.com@evil.com/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://localhost/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://127.0.0.1/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://0.0.0.0/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://[::1]/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://10.0.0.5/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://172.16.0.5/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://192.168.1.5/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://[fc00::1]/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://169.254.169.254/latest/meta-data/"),
            (ConnectorProvider.GITHUB, "https://api.github.com.evil.com/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://github.internal/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://example.com/repos/a/b"),
            (ConnectorProvider.GITHUB, "https://slack.com/api/conversations.list"),
            (ConnectorProvider.SLACK, "https://api.github.com/repos/a/b/issues"),
            (ConnectorProvider.LINEAR, "https://api.github.com/graphql"),
            (ConnectorProvider.GITHUB, ""),
            (ConnectorProvider.GITHUB, "not-a-url"),
        ],
    )
    def test_disallowed_provider_urls_fail_closed(self, provider, url):
        with pytest.raises(ProviderValidationError):
            assert_approved_provider_url(provider, url)

    async def test_redirect_to_unapproved_host_is_not_followed(self):
        """A 302 from the approved host must not trigger a second request
        to a redirect destination (follow_redirects=False)."""
        requested = []

        def handler(request):
            requested.append(str(request.url))
            return httpx.Response(302, headers={"Location": "https://127.0.0.1/steal"})

        adapter = GitHubProviderAdapter(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        with pytest.raises(ProviderTransportError):
            await adapter.fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="t"),
                "example/acme",
            )
        assert len(requested) == 1
        assert requested[0].startswith("https://api.github.com/repos/example/acme/issues")

    async def test_allowlist_guard_runs_before_any_request(self, monkeypatch):
        """Even if a bad URL somehow reaches the adapter, the allowlist
        rejects it before a request is issued."""
        called = False

        def handler(request):
            nonlocal called
            called = True
            return httpx.Response(200, json=[])

        transport = httpx.MockTransport(handler)
        adapter = GitHubProviderAdapter(client=httpx.AsyncClient(transport=transport))
        monkeypatch.setattr(
            "arc.services.connector_providers.github.GITHUB_ISSUES_URL",
            "https://127.0.0.1/repos/{target}/issues",
        )
        with pytest.raises(ProviderValidationError):
            await adapter.fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="t"),
                "example/acme",
            )
        assert not called


class TestProviderErrorMapping:
    """Provider failures normalize into controlled errors (no raw
    provider responses, bodies, or secrets reach callers)."""

    @pytest.mark.parametrize("status", [404, 409, 502, 503])
    async def test_github_unexpected_statuses_map_to_transport_error(self, status):
        def handler(request):
            return httpx.Response(status, json={"message": "raw provider body"})

        with pytest.raises(ProviderTransportError):
            await GitHubProviderAdapter(
                client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
            ).fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="t"),
                "example/acme",
            )

    async def test_github_timeout_maps_to_transport_error(self):
        def handler(request):
            raise httpx.ReadTimeout("timed out")

        with pytest.raises(ProviderTransportError):
            await GitHubProviderAdapter(
                client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
            ).fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="t"),
                "example/acme",
            )

    async def test_slack_unexpected_status_maps_to_transport_error(self):
        def handler(request):
            if request.url.path == "/api/conversations.list":
                return httpx.Response(502, json={"ok": False})
            return httpx.Response(502, json={"ok": False})

        with pytest.raises(ProviderTransportError):
            await SlackProviderAdapter(
                client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
            ).fetch(
                ProviderCredential(provider=ConnectorProvider.SLACK, token="t"),
                "general",
            )

    async def test_linear_unexpected_status_maps_to_transport_error(self):
        def handler(request):
            return httpx.Response(503, json={"errors": []})

        with pytest.raises(ProviderTransportError):
            await LinearProviderAdapter(
                client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
            ).fetch(
                ProviderCredential(provider=ConnectorProvider.LINEAR, token="t"),
                "abc",
            )

    async def test_errors_never_contain_credential_material(self):
        def handler(request):
            return httpx.Response(401, json={"message": "token=t-secret"})

        with pytest.raises(ProviderAuthError) as exc_info:
            await GitHubProviderAdapter(
                client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
            ).fetch(
                ProviderCredential(provider=ConnectorProvider.GITHUB, token="t-secret"),
                "example/acme",
            )
        assert "t-secret" not in str(exc_info.value)
        assert "t-secret" not in str(exc_info.value.__cause__)


class TestProviderModeGate:
    """Live mode must never become implicitly authorized by existence."""

    def test_simulated_mode_builds_fake_adapters_only(self):
        registry = build_provider_registry(ConnectorSettings(provider_mode="simulated"))
        assert isinstance(registry.get(ConnectorProvider.GITHUB), FakeGitHubProvider)
        assert isinstance(registry.get(ConnectorProvider.SLACK), FakeSlackProvider)
        assert isinstance(registry.get(ConnectorProvider.LINEAR), FakeLinearProvider)

    def test_live_mode_requires_explicit_configuration(self):
        registry = build_provider_registry(ConnectorSettings(provider_mode="live"))
        assert isinstance(registry.get(ConnectorProvider.GITHUB), GitHubProviderAdapter)
        assert isinstance(registry.get(ConnectorProvider.SLACK), SlackProviderAdapter)
        assert isinstance(registry.get(ConnectorProvider.LINEAR), LinearProviderAdapter)

    def test_default_settings_never_enable_live_adapters(self, monkeypatch):
        monkeypatch.delenv("CONNECTOR_PROVIDER_MODE", raising=False)
        settings = get_connector_settings()
        assert settings.provider_mode == "simulated"
        registry = build_provider_registry(settings)
        assert all(
            not isinstance(
                registry.get(p),
                (GitHubProviderAdapter, SlackProviderAdapter, LinearProviderAdapter),
            )
            for p in (ConnectorProvider.GITHUB, ConnectorProvider.SLACK, ConnectorProvider.LINEAR)
        )
