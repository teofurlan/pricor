"""Tests for the Google OIDC ID token verifier adapter."""

import pytest

from pricor.adapters.google_auth import GoogleOidcVerifier
from pricor.ports.google_auth import GoogleIdentity, InvalidGoogleTokenError


def test_verifier_requires_non_empty_client_id():
    with pytest.raises(ValueError):
        GoogleOidcVerifier("")
    with pytest.raises(ValueError):
        GoogleOidcVerifier("   ")


def test_verify_rejects_empty_credential_without_calling_verifier():
    called = False

    def verify_fn(token: str, request: object, audience: str) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    verifier = GoogleOidcVerifier("client-123", verify_fn=verify_fn)

    with pytest.raises(InvalidGoogleTokenError, match="empty"):
        verifier.verify("")
    with pytest.raises(InvalidGoogleTokenError, match="empty"):
        verifier.verify("   \t\n ")
    assert called is False


def test_verify_accepts_valid_google_claims_and_trims_values():
    received: list[tuple[str, str]] = []

    def verify_fn(token: str, request: object, audience: str) -> dict[str, object]:
        received.append((token, audience))
        return {
            "iss": "https://accounts.google.com",
            "email_verified": True,
            "sub": " 10987654321 ",
            "email": " ada@example.com ",
        }

    verifier = GoogleOidcVerifier("  client-123.apps.googleusercontent.com  ", verify_fn=verify_fn)
    identity = verifier.verify("  header.payload.sig  ")

    assert identity == GoogleIdentity(sub="10987654321", email="ada@example.com")
    assert received == [("header.payload.sig", "client-123.apps.googleusercontent.com")]


def test_verify_accepts_accounts_google_com_without_scheme():
    verifier = GoogleOidcVerifier(
        "client-123",
        verify_fn=lambda *_: {
            "iss": "accounts.google.com",
            "email_verified": True,
            "sub": "sub-1",
            "email": "user@example.com",
        },
    )

    assert verifier.verify("tok") == GoogleIdentity(sub="sub-1", email="user@example.com")


def test_verify_wraps_verifier_exceptions_as_invalid_google_token_error():
    def failing_verify(*_: object) -> dict[str, object]:
        raise ValueError("Token has wrong audience")

    verifier = GoogleOidcVerifier("client-123", verify_fn=failing_verify)

    with pytest.raises(InvalidGoogleTokenError, match="invalid Google ID token"):
        verifier.verify("bad.token")


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://evil.example.com", "email_verified": True, "sub": "1", "email": "a@b.com"},
        {"iss": None, "email_verified": True, "sub": "1", "email": "a@b.com"},
        {"iss": "https://accounts.google.com", "email_verified": False, "sub": "1", "email": "a@b.com"},
        {"iss": "https://accounts.google.com", "email_verified": "true", "sub": "1", "email": "a@b.com"},
        {"iss": "https://accounts.google.com", "email_verified": True, "sub": "", "email": "a@b.com"},
        {"iss": "https://accounts.google.com", "email_verified": True, "sub": "   ", "email": "a@b.com"},
        {"iss": "https://accounts.google.com", "email_verified": True, "sub": 123, "email": "a@b.com"},
        {"iss": "https://accounts.google.com", "email_verified": True, "sub": "1", "email": ""},
        {"iss": "https://accounts.google.com", "email_verified": True, "sub": "1", "email": "   "},
        {"iss": "https://accounts.google.com", "email_verified": True, "sub": "1", "email": None},
    ],
)
def test_verify_rejects_invalid_claims(claims):
    verifier = GoogleOidcVerifier("client-123", verify_fn=lambda *_: claims)

    with pytest.raises(InvalidGoogleTokenError):
        verifier.verify("tok")
