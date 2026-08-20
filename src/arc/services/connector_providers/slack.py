"""Slack connector adapter (PRD 22, TRD 33, ADR-002).

Live mode calls the code-defined Slack Web API: the channel list is
resolved by name (never by tenant-supplied URLs) and messages are fetched
from the channel history. Responses carry Slack's ``ok`` flag and are
validated; unexpected shapes fail closed.
"""

import re
from typing import Any, Dict, Optional

import httpx

from arc.domain.models import ConnectorProvider
from arc.services.connector_providers.base import (
    ProviderAuthError,
    ProviderCredential,
    ProviderFetchResult,
    ProviderRateLimitError,
    ProviderRecord,
    ProviderResponseError,
    ProviderTransportError,
    ProviderValidationError,
)
from arc.services.connector_providers.targets import assert_approved_provider_url

SLACK_CONVERSATIONS_LIST_URL = "https://slack.com/api/conversations.list"
SLACK_CONVERSATIONS_HISTORY_URL = "https://slack.com/api/conversations.history"

_SLACK_CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

_DEFAULT_TIMEOUT = httpx.Timeout(10.0)

_AUTH_ERRORS = {"invalid_auth", "account_inactive", "token_revoked", "not_authed"}


def validate_slack_target(target: str) -> str:
    """Validate a Slack connector target (channel name)."""
    if not target or not _SLACK_CHANNEL_RE.match(target):
        raise ProviderValidationError(
            "Slack connector target must be a channel name (lowercase letters, digits, dashes)"
        )
    return target


class SlackProviderAdapter:
    """httpx-based Slack adapter; endpoints are code-defined constants."""

    provider = ConnectorProvider.SLACK

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client

    async def fetch(
        self,
        credential: ProviderCredential,
        target: str,
        limit: int = 25,
    ) -> ProviderFetchResult:
        validate_slack_target(target)
        channel_id = await self._resolve_channel_id(credential, target)
        headers = {"Authorization": f"Bearer {credential.token}"}
        params: Dict[str, Any] = {"channel": channel_id, "limit": max(1, min(int(limit), 100))}
        response = await self._request(
            "GET", SLACK_CONVERSATIONS_HISTORY_URL, headers=headers, params=params
        )
        payload = response.json()
        _assert_slack_ok(payload)
        messages = payload.get("messages", [])
        records = [
            _parse_slack_message(message, target)
            for message in messages
            if isinstance(message, dict)
        ]
        return ProviderFetchResult(provider=self.provider, records=records)

    async def _resolve_channel_id(self, credential: ProviderCredential, target: str) -> str:
        headers = {"Authorization": f"Bearer {credential.token}"}
        response = await self._request("GET", SLACK_CONVERSATIONS_LIST_URL, headers=headers)
        payload = response.json()
        _assert_slack_ok(payload)
        channels = payload.get("channels", [])
        if not isinstance(channels, list):
            raise ProviderResponseError("Slack channels response must be a list")
        for channel in channels:
            if isinstance(channel, dict) and channel.get("name") == target:
                channel_id = channel.get("id")
                if isinstance(channel_id, str) and channel_id:
                    return channel_id
        raise ProviderValidationError(f"Slack channel '{target}' was not found")

    async def _request(self, method: str, url: str, **kwargs):
        assert_approved_provider_url(self.provider, url)
        owns_client = self._client is None
        client = (
            self._client
            if self._client is not None
            else httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=False)
        )
        try:
            try:
                response = await client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                raise ProviderTransportError("Slack request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code == 429:
            raise ProviderRateLimitError("Slack rate limit exceeded")
        if response.status_code in (401, 403):
            raise ProviderAuthError("Slack authentication failed")
        if response.status_code >= 500:
            raise ProviderTransportError("Slack service unavailable")
        if response.status_code != 200:
            raise ProviderTransportError(f"Slack returned status {response.status_code}")
        return response


def _assert_slack_ok(payload: Any) -> None:
    """Validate Slack's ``ok`` envelope; map common error strings."""
    if not isinstance(payload, dict):
        raise ProviderResponseError("Slack response must be an object")
    if payload.get("ok") is True:
        return
    error = payload.get("error")
    if error in _AUTH_ERRORS:
        raise ProviderAuthError("Slack authentication failed")
    if error == "ratelimited":
        raise ProviderRateLimitError("Slack rate limit exceeded")
    raise ProviderResponseError(f"Slack returned an error response: {error}")


def _parse_slack_message(message: Dict[str, Any], channel: str) -> ProviderRecord:
    text = message.get("text")
    ts = message.get("ts")
    if not isinstance(text, str) or not text or not isinstance(ts, str) or not ts:
        raise ProviderResponseError("Slack message is missing required fields")
    return ProviderRecord(
        source_id=f"slack-{channel}-{ts}",
        title=f"Slack message in #{channel}",
        content=f"Slack message in #{channel}:\n\n{text}".strip(),
    )
