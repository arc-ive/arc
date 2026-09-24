"""GitHub connector adapter (PRD 22, TRD 33, ADR-002).

Live mode calls the code-defined GitHub REST endpoint. The target is
``owner/repo`` and is validated before any request is made; tenant input
never selects a network destination. Responses are validated into typed
records; unexpected shapes fail closed.
"""

import re
from typing import Any, Dict, List, Optional

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

GITHUB_ISSUES_URL = "https://api.github.com/repos/{target}/issues"

_GITHUB_TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

_DEFAULT_TIMEOUT = httpx.Timeout(10.0)


def validate_github_target(target: str) -> str:
    """Validate a GitHub connector target (``owner/repo``)."""
    if not target or not _GITHUB_TARGET_RE.match(target):
        raise ProviderValidationError("GitHub connector target must be 'owner/repo'")
    return target


class GitHubProviderAdapter:
    """httpx-based GitHub adapter; endpoints are code-defined constants."""

    provider = ConnectorProvider.GITHUB

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client

    async def fetch(
        self,
        credential: ProviderCredential,
        target: str,
        limit: int = 25,
    ) -> ProviderFetchResult:
        validate_github_target(target)
        url = GITHUB_ISSUES_URL.format(target=target)
        headers = {
            "Authorization": f"Bearer {credential.token}",
            "Accept": "application/vnd.github+json",
        }
        params: Dict[str, Any] = {"state": "all", "per_page": max(1, min(int(limit), 100))}
        response = await self._request("GET", url, headers=headers, params=params)
        return ProviderFetchResult(
            provider=self.provider, records=_parse_github_issues(response.json(), target)
        )

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
                raise ProviderTransportError("GitHub request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code in (401, 403):
            raise ProviderAuthError("GitHub authentication failed")
        if response.status_code == 429:
            raise ProviderRateLimitError("GitHub rate limit exceeded")
        if response.status_code >= 500:
            raise ProviderTransportError("GitHub service unavailable")
        if response.status_code != 200:
            raise ProviderTransportError(f"GitHub returned status {response.status_code}")
        return response


def _parse_github_issues(payload: Any, container: str) -> List[ProviderRecord]:
    """Validate a GitHub issues response into typed records.

    Source metadata contract (Issue #326): preserves the author
    (``user.login``), provider timestamps (``created_at``/``updated_at``),
    and container identity (the validated ``owner/repo`` target) that the
    response already carries. Deliberately dropped (no consumer yet):
    labels, assignees, state, comment counts, reactions, timeline events.
    Pull-request payloads and comments are a later scope, not this parser.
    Required-field failures still fail closed; absent optional metadata
    degrades to ``None``, never to an invented value.
    """
    if not isinstance(payload, list):
        raise ProviderResponseError("GitHub issues response must be a list")
    records: List[ProviderRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ProviderResponseError("GitHub issue must be an object")
        number = item.get("number")
        title = item.get("title")
        body = item.get("body")
        html_url = item.get("html_url")
        if number is None or not isinstance(title, str) or not title:
            raise ProviderResponseError("GitHub issue is missing required fields")
        body_text = body.strip() if isinstance(body, str) else ""
        content = f"Issue #{number}: {title}\n\n{body_text}".strip()
        records.append(
            ProviderRecord(
                source_id=f"github-issue-{number}",
                title=title,
                content=content,
                url=str(html_url) if html_url else None,
                author=_optional_str(_author_login(item.get("user"))),
                external_created_at=_optional_str(item.get("created_at")),
                external_updated_at=_optional_str(item.get("updated_at")),
                container_id=container,
            )
        )
    return records


def _author_login(user: Any) -> Optional[str]:
    """Extract the author login from a GitHub ``user`` object, if present."""
    if isinstance(user, dict):
        login = user.get("login")
        if isinstance(login, str) and login:
            return login
    return None


def _optional_str(value: Any) -> Optional[str]:
    """Pass through a present non-empty string, else ``None`` (absent)."""
    if isinstance(value, str) and value:
        return value
    return None
