"""Verify user access tokens against the configured Supabase project."""
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from time import monotonic, time
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
import httpx
import jwt

from backend.config import settings
from backend.contracts.rest import bearer
from backend.run_worker.store import StoreError

ALGORITHMS = {"ES256": ("EC", "P-256"), "RS256": ("RSA", None)}
CLAIMS = ["sub", "exp", "iss", "aud"]


@dataclass(frozen=True)
class Owner:
    subject: str
    expires_at: float


class SupabaseKeys:
    def __init__(self, issuer):
        self.issuer = issuer
        self.keys = {}
        self.expires = 0
        self.refresh_after = 0
        self.lock = Lock()

    def _refresh(self, now):
        self.refresh_after = now + 10
        try:
            response = httpx.get(self.issuer + "/.well-known/jwks.json", timeout=3, follow_redirects=False)
            response.raise_for_status()
            keys = {}
            for key in response.json()["keys"]:
                alg = key.get("alg")
                kid = key.get("kid")
                if alg not in ALGORITHMS or not isinstance(kid, str) or not kid or key.get("use", "sig") != "sig":
                    continue
                key_type, curve = ALGORITHMS[alg]
                if key.get("kty") != key_type or (curve and key.get("crv") != curve):
                    continue
                if kid in keys:
                    raise ValueError("Duplicate key ID")
                keys[kid] = jwt.PyJWK.from_dict(key, algorithm=alg)
            if not keys:
                raise ValueError("No supported signing keys")
        except (httpx.HTTPError, jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError):
            return
        self.keys, self.expires = keys, monotonic() + 300

    def get(self, kid=None):
        with self.lock:
            now = monotonic()
            if (now >= self.expires or (kid is not None and kid not in self.keys)) and now >= self.refresh_after:
                self._refresh(now)
            if monotonic() >= self.expires:
                raise StoreError(503, "service_unavailable", "Identity provider temporarily unavailable")
            return self.keys.get(kid)


@lru_cache(maxsize=4)
def supabase_keys(issuer):
    return SupabaseKeys(issuer)


def owner(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    try:
        issuer = settings.supabase_issuer if settings.uses_supabase else settings.v1_jwt_issuer
        if not settings.uses_supabase and len(settings.v1_jwt_secret) < 32:
            raise ValueError("Missing local authentication key")
    except ValueError:
        raise StoreError(503, "service_unavailable", "Authentication is not configured") from None
    if credentials is None or len(credentials.credentials) > 16384:
        raise StoreError(401, "unauthorized", "Bearer token required")
    token = credentials.credentials
    try:
        if settings.uses_supabase:
            header = jwt.get_unverified_header(token)
            alg, kid = header.get("alg"), header.get("kid")
            if not isinstance(alg, str) or alg not in ALGORITHMS or not isinstance(kid, str) or not 1 <= len(kid) <= 200:
                raise jwt.InvalidTokenError()
            key = supabase_keys(issuer).get(kid)
            if key is None or key.algorithm_name != alg:
                raise jwt.InvalidTokenError()
            claims = jwt.decode(token, key.key, algorithms=[alg], audience="authenticated",
                                issuer=issuer, options={"require": [*CLAIMS, "iat", "session_id", "role"]})
            if claims["role"] != "authenticated" or claims.get("is_anonymous", False) is not False:
                raise jwt.InvalidTokenError()
            UUID(claims["session_id"])
            subject = f"{issuer}|{UUID(claims['sub'])}"
        else:
            claims = jwt.decode(token, settings.v1_jwt_secret, algorithms=["HS256"],
                                audience=settings.v1_jwt_audience, issuer=issuer, options={"require": CLAIMS})
            subject = claims["sub"]
            if not subject or len(subject) > 200:
                raise jwt.InvalidTokenError()
        expires_at = claims["exp"]
        if type(expires_at) is not int or expires_at <= time():
            raise jwt.InvalidTokenError()
        return Owner(subject, expires_at)
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError, OverflowError):
        raise StoreError(401, "unauthorized", "Invalid or expired bearer token") from None
