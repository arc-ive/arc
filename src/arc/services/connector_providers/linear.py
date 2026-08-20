"""Linear connector adapter (PRD 22, TRD 33, ADR-002).

Live mode calls the code-defined Linear GraphQL endpoint with a fixed
query. The target is a team key and is validated before any request is
made. Responses are validated into typed records; GraphQL error blocks
fail closed.
"""

import re
from typing import Any, List, Optional

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

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"

_LINEAR_TEAM_RE = re.compile(r"^[A-Za-z0-9-]{1,16}$")

_DEFAULT_TIMEOUT = httpx.Timeout(10.0)

_TEAM_ISSUES_QUERY = """
query TeamIssues($teamKey: String!, $first: Int!) {
  team(key: $teamKey) {
    issues(first: $first, orderBy: updatedAt) {
      nodes {
        identifier
        title
        description
        url
      }
    }
  }
}
"""


def validate_linear_target(target: str) -> str:
    """Validate a Linear connector target (team key)."""
    if not target or not _LINEAR_TEAM_RE.match(target):
        raise ProviderValidationError(
            "Linear connector target must be a team key (letters, digits, dashes)"
        )
    return target


class LinearProviderAdapter:
    """httpx-based Linear adapter; the endpoint and query are code-defined."""

    provider = ConnectorProvider.LINEAR

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client

    async def fetch(
        self,
        credential: ProviderCredential,
        target: str,
        limit: int = 25,
    ) -> ProviderFetchResult:
        validate_linear_target(target)
        headers = {
            "Authorization": credential.token,
            "Content-Type": "application/json",
        }
        body = {
            "query": _TEAM_ISSUES_QUERY,
            "variables": {"teamKey": target, "first": max(1, min(int(limit), 100))},
        }
        response = await self._request("POST", LINEAR_GRAPHQL_URL, headers=headers, json=body)
        payload = response.json()
        return ProviderFetchResult(provider=self.provider, records=_parse_linear_issues(payload))

    async def _request(self, method: str, url: str, **kwargs):
        owns_client = self._client is None
        client = (
            self._client
            if self._client is not None
            else httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        )
        try:
            try:
                response = await client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                raise ProviderTransportError("Linear request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code in (401, 403):
            raise ProviderAuthError("Linear authentication failed")
        if response.status_code == 429:
            raise ProviderRateLimitError("Linear rate limit exceeded")
        if response.status_code >= 500:
            raise ProviderTransportError("Linear service unavailable")
        if response.status_code != 200:
            raise ProviderTransportError(f"Linear returned status {response.status_code}")
        return response


def _parse_linear_issues(payload: Any) -> List[ProviderRecord]:
    """Validate a Linear GraphQL response into typed records."""
    if not isinstance(payload, dict):
        raise ProviderResponseError("Linear response must be an object")
    if payload.get("errors"):
        raise ProviderResponseError("Linear returned a GraphQL error response")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ProviderResponseError("Linear response is missing data")
    team = data.get("team")
    if not isinstance(team, dict):
        raise ProviderResponseError("Linear team is missing from the response")
    issues = team.get("issues", {})
    if not isinstance(issues, dict):
        raise ProviderResponseError("Linear issues must be an object")
    nodes = issues.get("nodes")
    if not isinstance(nodes, list):
        raise ProviderResponseError("Linear issue nodes must be a list")

    records: List[ProviderRecord] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ProviderResponseError("Linear issue must be an object")
        identifier = node.get("identifier")
        title = node.get("title")
        if not isinstance(identifier, str) or not identifier:
            raise ProviderResponseError("Linear issue is missing its identifier")
        if not isinstance(title, str) or not title:
            raise ProviderResponseError("Linear issue is missing its title")
        description = node.get("description") or ""
        url = node.get("url")
        content = f"{identifier}: {title}\n\n{description}".strip()
        records.append(
            ProviderRecord(
                source_id=f"linear-{identifier}",
                title=title,
                content=content,
                url=str(url) if url else None,
            )
        )
    return records
