"""X-11 authentication tests: JWT bearer credentials.

These tests exercise the authentication boundary only. The JWT ``sub`` is
the exclusive source of the authenticated user identity; client-supplied
user identifiers can never override it.
"""

import jwt as pyjwt
import pytest

from arc.security.jwt import AuthenticationError, JwtService
from arc.security.models import AuthenticatedPrincipal
from arc.security.settings import (
    SecurityConfigurationError,
    SecuritySettings,
    get_security_settings,
)


def test_public_health_endpoint_requires_no_authentication(client):
    """Regression: /health stays public; the security layer must not break it."""
    response = client.get("/health")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer not-a-jwt"},
        {"X-User-Id": "user-1"},
    ],
)
def test_missing_or_malformed_credentials_are_rejected(client, headers):
    """Any missing/malformed credential must produce a generic 401."""
    response = client.get("/users/user-1/tenants", headers=headers)
    assert response.status_code == 401


def test_invalid_signature_is_rejected(client, wrong_secret_token):
    """A token signed with a different secret must be rejected."""
    token = wrong_secret_token("user-1")
    response = client.get("/users/user-1/tenants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_expired_token_is_rejected(client, make_token):
    """An expired token must be rejected even though the signature is valid."""
    token = make_token("user-1", expires_in_seconds=-10)
    response = client.get("/users/user-1/tenants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_wrong_issuer_is_rejected(client, make_token):
    token = make_token("user-1", issuer="other-issuer")
    response = client.get("/users/user-1/tenants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_wrong_audience_is_rejected(client, make_token):
    token = make_token("user-1", audience="other-audience")
    response = client.get("/users/user-1/tenants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_valid_token_is_accepted_for_self(client, make_token):
    """A valid JWT authenticates; the identity comes from the JWT ``sub``."""
    token = make_token("user-1")
    response = client.get("/users/user-1/tenants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_client_supplied_user_id_cannot_override_jwt_identity(client, make_token):
    """The JWT identity is authoritative; a conflicting path user_id is denied."""
    token = make_token("user-1")
    response = client.get("/users/user-2/tenants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_identity_cannot_be_injected_via_query_or_headers(client, make_token):
    """Query params / headers cannot smuggle a conflicting user identity."""
    token = make_token("user-1")
    response = client.get(
        "/users/user-2/tenants",
        headers={"Authorization": f"Bearer {token}", "X-User-Id": "user-1"},
        params={"user_id": "user-1"},
    )
    assert response.status_code == 403


def test_no_user_id_in_token_is_rejected():
    """A token without a ``sub`` claim must not produce a principal."""
    settings = get_security_settings()
    unsigned = pyjwt.encode({}, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        JwtService(settings).decode_access_token(unsigned)


def test_algorithm_allow_list_rejects_none():
    """The algorithm allow-list must reject an unsigned "none" token."""
    settings = get_security_settings()
    unsigned = pyjwt.encode({"sub": "user-1"}, None, algorithm="none")
    with pytest.raises(AuthenticationError):
        JwtService(settings).decode_access_token(unsigned)


def test_token_without_required_claims_is_rejected():
    """Missing issuer/audience claims must be rejected."""
    settings = get_security_settings()
    bare = pyjwt.encode({"sub": "user-1"}, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        JwtService(settings).decode_access_token(bare)


def test_principal_derived_from_jwt_sub():
    """The authenticated principal's user_id is exactly the JWT ``sub``."""
    settings = get_security_settings()
    service = JwtService(settings)
    token = service.create_access_token("principal-123")
    assert service.decode_access_token(token) == "principal-123"
    assert AuthenticatedPrincipal(user_id="principal-123").user_id == "principal-123"


def test_security_settings_require_minimum_secret_length():
    """A too-short JWT secret must fail closed at configuration time."""
    with pytest.raises(SecurityConfigurationError):
        SecuritySettings(jwt_secret="short")
