"""Cloudflare Access assertion verification and explicit local role authorization."""

from __future__ import annotations

import json
import re
from pathlib import Path

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWTError


class AuthenticationError(Exception):
    """An assertion is missing, invalid, or expired."""


class VerificationUnavailable(Exception):
    """Signing keys cannot currently be obtained or checked."""


class AuthorizationError(Exception):
    """A verified identity has no console role."""


_ISSUER = re.compile(r"https://[a-zA-Z0-9-]+\.cloudflareaccess\.com\Z")
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\Z")


class RolePolicy:
    """Immutable, server-side Viewer/Administrator allowlist loaded at startup."""

    def __init__(self, viewers: set[str], administrators: set[str]):
        self.viewers = frozenset(viewers)
        self.administrators = frozenset(administrators)
        if not (self.viewers or self.administrators) or self.viewers & self.administrators:
            raise ValueError("role allowlist must be nonempty and roles must not overlap")

    @classmethod
    def from_file(cls, path: str | Path) -> "RolePolicy":
        path = Path(path)
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 65_536:
            raise ValueError("role policy file is unavailable or unsafe")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {"viewer", "administrator"}:
            raise ValueError("role policy must contain viewer and administrator lists")
        roles = {}
        for role, members in value.items():
            if not isinstance(members, list) or any(not isinstance(item, str) or not _EMAIL.fullmatch(item) for item in members):
                raise ValueError("invalid role member")
            normalized = {member.casefold() for member in members}
            if len(normalized) != len(members):
                raise ValueError("duplicate role member")
            roles[role] = normalized
        return cls(roles["viewer"], roles["administrator"])

    def role_for(self, email: str) -> str:
        if email in self.administrators:
            return "administrator"
        if email in self.viewers:
            return "viewer"
        raise AuthorizationError("identity has no console role")


class CloudflareAccessVerifier:
    """Verify Cloudflare's RS256 application JWT using the issuer's rotating JWKS."""

    def __init__(self, issuer: str, audience: str, *, jwks_client=None):
        if not _ISSUER.fullmatch(issuer) or not isinstance(audience, str) or not audience.strip() or len(audience) > 256:
            raise ValueError("invalid Cloudflare Access issuer or audience")
        self.issuer = issuer
        self.audience = audience
        self.jwks_client = jwks_client or PyJWKClient(
            issuer + "/cdn-cgi/access/certs", cache_jwk_set=True, lifespan=300, timeout=3
        )

    def verify(self, token: str) -> str:
        if not isinstance(token, str) or not token or len(token) > 16_384:
            raise AuthenticationError("missing or oversized assertion")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str) or len(header["kid"]) > 256:
                raise AuthenticationError("unsupported assertion header")
            key = self.jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, key.key, algorithms=["RS256"], issuer=self.issuer, audience=self.audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=0,
            )
        except PyJWKClientConnectionError as exc:
            raise VerificationUnavailable("Access signing keys unavailable") from exc
        except (PyJWTError, PyJWKClientError, ValueError, TypeError) as exc:
            raise AuthenticationError("invalid Access assertion") from exc
        email = claims.get("email")
        if not isinstance(email, str) or not _EMAIL.fullmatch(email):
            raise AuthenticationError("assertion has no valid user email")
        return email.casefold()


class ConsoleAuthorization:
    def __init__(self, verifier: CloudflareAccessVerifier, roles: RolePolicy):
        self.verifier = verifier
        self.roles = roles

    def authorize(self, token: str) -> str:
        return self.roles.role_for(self.verifier.verify(token))
