"""Google OIDC ID token verifier backed by google-auth."""

from collections.abc import Callable, Mapping
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from pricor.ports.google_auth import GoogleIdentity, InvalidGoogleTokenError

_VALID_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class GoogleOidcVerifier:
    """Verifies Google ID tokens against the configured OAuth client ID."""

    def __init__(
        self,
        client_id: str,
        verify_fn: Callable[[str, Any, str], Mapping[str, Any]] | None = None,
    ) -> None:
        cleaned = client_id.strip() if isinstance(client_id, str) else ""
        if not cleaned:
            raise ValueError("Google client_id must be a non-empty string")
        self._client_id = cleaned
        self._verify_fn = verify_fn or id_token.verify_oauth2_token
        self._request = google_requests.Request()

    def verify(self, credential: str) -> GoogleIdentity:
        if not isinstance(credential, str) or not credential.strip():
            raise InvalidGoogleTokenError("Google credential is empty")

        try:
            claims = self._verify_fn(credential.strip(), self._request, self._client_id)
        except Exception as error:
            raise InvalidGoogleTokenError("invalid Google ID token") from error

        if not isinstance(claims, Mapping):
            raise InvalidGoogleTokenError("invalid Google ID token")
        if claims.get("iss") not in _VALID_ISSUERS:
            raise InvalidGoogleTokenError("invalid Google ID token issuer")
        if claims.get("email_verified") is not True:
            raise InvalidGoogleTokenError("Google account email is not verified")

        sub = claims.get("sub")
        email = claims.get("email")
        if not isinstance(sub, str) or not sub.strip():
            raise InvalidGoogleTokenError("Google ID token missing subject")
        if not isinstance(email, str) or not email.strip():
            raise InvalidGoogleTokenError("Google ID token missing email")

        return GoogleIdentity(sub=sub.strip(), email=email.strip())
