"""Access token verification.

The previous implementation opened a fresh TLS connection to Supabase's
``/auth/v1/user`` endpoint for every single API call. With the frontend polling
once a second that was one full round-trip per second per open tab, it made the
Auth service a hard dependency of every read, and it dominated the latency of
otherwise trivial endpoints.

Two things fix that, in order of preference:

* verify the signature locally when the project's JWT secret is configured;
* otherwise call Supabase, but reuse the connection and cache the result for a
  short window that never outlives the token itself.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from uuid import UUID

import requests
from fastapi import Header, HTTPException
from pydantic import BaseModel

from backend.config import get_settings


_MAX_CACHE_ENTRIES = 2048


class CurrentUser(BaseModel):
    id: UUID
    email: str | None = None


class _TokenCache:
    """Small TTL cache keyed by the raw access token."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, CurrentUser]] = {}

    def get(self, token: str) -> CurrentUser | None:
        now = time.time()

        with self._lock:
            entry = self._entries.get(token)

            if entry is None:
                return None

            expires_at, user = entry

            if expires_at <= now:
                self._entries.pop(token, None)
                return None

            return user

    def put(self, token: str, user: CurrentUser, expires_at: float) -> None:
        if expires_at <= time.time():
            return

        with self._lock:
            if len(self._entries) >= _MAX_CACHE_ENTRIES:
                now = time.time()
                stale = [
                    key
                    for key, (entry_expiry, _) in self._entries.items()
                    if entry_expiry <= now
                ]

                for key in stale:
                    self._entries.pop(key, None)

                if len(self._entries) >= _MAX_CACHE_ENTRIES:
                    self._entries.clear()

            self._entries[token] = (expires_at, user)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_cache = _TokenCache()
_http = requests.Session()


def reset_auth_cache() -> None:
    """Exposed for tests and for operational recovery."""

    _cache.clear()


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _decode_segment(segment: str) -> dict:
    try:
        payload = json.loads(_b64url_decode(segment))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Malformed access token") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Malformed access token")

    return payload


def _split_token(token: str) -> tuple[dict, dict, str, bytes]:
    parts = token.split(".")

    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Malformed access token")

    header = _decode_segment(parts[0])
    claims = _decode_segment(parts[1])

    return header, claims, f"{parts[0]}.{parts[1]}", _b64url_decode(parts[2])


def _user_from_claims(claims: dict) -> CurrentUser:
    subject = claims.get("sub")

    if not subject:
        raise HTTPException(status_code=401, detail="Access token has no subject")

    try:
        user_id = UUID(str(subject))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Access token subject is invalid") from exc

    return CurrentUser(id=user_id, email=claims.get("email"))


def _verify_locally(token: str, secret: str) -> tuple[CurrentUser, float] | None:
    """Return the user when the token is a valid HS256 token, else None.

    Returning None means "cannot decide locally"; an invalid signature or an
    expired token raises instead, so a forged token never falls through to a
    slower path that might accept it.
    """

    header, claims, signing_input, signature = _split_token(token)

    if header.get("alg") != "HS256":
        return None

    expected = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    expires_at = claims.get("exp")

    if not isinstance(expires_at, (int, float)) or expires_at <= time.time():
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return _user_from_claims(claims), float(expires_at)


def _token_expiry(token: str) -> float | None:
    try:
        _, claims, _, _ = _split_token(token)
    except HTTPException:
        return None

    expires_at = claims.get("exp")

    if isinstance(expires_at, (int, float)):
        return float(expires_at)

    return None


def _verify_with_supabase(token: str) -> CurrentUser:
    settings = get_settings()

    try:
        response = _http.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": settings.supabase_publishable_key,
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to verify session with Supabase",
        ) from exc

    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if response.status_code >= 400:
        raise HTTPException(
            status_code=503,
            detail="Unable to verify session with Supabase",
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to verify session with Supabase",
        ) from exc

    return _user_from_claims(
        {"sub": data.get("id"), "email": data.get("email")}
    )


def verify_access_token(token: str) -> CurrentUser:
    token = token.strip()

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    cached = _cache.get(token)

    if cached is not None:
        return cached

    settings = get_settings()

    if settings.supabase_jwt_secret:
        verified = _verify_locally(token, settings.supabase_jwt_secret)

        if verified is not None:
            user, expires_at = verified
            _cache.put(token, user, expires_at)
            return user

    user = _verify_with_supabase(token)

    ttl_expiry = time.time() + settings.auth_cache_seconds
    token_expiry = _token_expiry(token)

    _cache.put(
        token,
        user,
        min(ttl_expiry, token_expiry) if token_expiry else ttl_expiry,
    )

    return user


def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    return verify_access_token(authorization.split(" ", 1)[1])
