"""Access token verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException

from backend import auth
from backend.config import get_settings


SECRET = "super-secret-jwt-signing-key"


def b64(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def make_token(claims: dict, *, secret: str = SECRET, alg: str = "HS256") -> str:
    header = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    signing_input = f"{header}.{body}"

    signature = hmac.new(
        secret.encode(), signing_input.encode(), hashlib.sha256
    ).digest()

    return f"{signing_input}.{b64(signature)}"


@pytest.fixture
def local_verification(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    get_settings.cache_clear()
    auth.reset_auth_cache()

    yield

    get_settings.cache_clear()
    auth.reset_auth_cache()


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if a code path reaches out to Supabase."""

    calls = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("unexpected call to Supabase Auth")

    monkeypatch.setattr(auth._http, "get", forbidden)
    return calls


VALID_USER = "6b1ec2f4-0b1f-4c66-9c0b-9a2d9f4d0f11"


def claims(**overrides) -> dict:
    body = {
        "sub": VALID_USER,
        "email": "player@test.dev",
        "exp": int(time.time()) + 3600,
    }
    body.update(overrides)
    return body


def test_a_valid_token_is_verified_without_calling_supabase(
    local_verification, no_network
):
    user = auth.verify_access_token(make_token(claims()))

    assert str(user.id) == VALID_USER
    assert user.email == "player@test.dev"


def test_a_tampered_payload_is_rejected(local_verification, no_network):
    token = make_token(claims())
    header, _, signature = token.split(".")

    forged = b64(json.dumps(claims(sub="00000000-0000-0000-0000-000000000000")).encode())

    with pytest.raises(HTTPException) as error:
        auth.verify_access_token(f"{header}.{forged}.{signature}")

    assert error.value.status_code == 401


def test_a_token_signed_with_the_wrong_key_is_rejected(
    local_verification, no_network
):
    with pytest.raises(HTTPException) as error:
        auth.verify_access_token(make_token(claims(), secret="not-the-secret"))

    assert error.value.status_code == 401


def test_an_expired_token_is_rejected(local_verification, no_network):
    with pytest.raises(HTTPException) as error:
        auth.verify_access_token(make_token(claims(exp=int(time.time()) - 1)))

    assert error.value.status_code == 401


def test_a_token_without_a_subject_is_rejected(local_verification, no_network):
    body = claims()
    body.pop("sub")

    with pytest.raises(HTTPException) as error:
        auth.verify_access_token(make_token(body))

    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "token", ["", "not-a-jwt", "only.two", "a.b.c.d", "...."]
)
def test_malformed_tokens_are_rejected(local_verification, no_network, token):
    with pytest.raises(HTTPException) as error:
        auth.verify_access_token(token)

    assert error.value.status_code == 401


def test_a_non_hs256_token_falls_back_to_supabase(local_verification, monkeypatch):
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id": VALID_USER, "email": "player@test.dev"}

    def fake_get(url, **kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr(auth._http, "get", fake_get)

    user = auth.verify_access_token(make_token(claims(), alg="ES256"))

    assert str(user.id) == VALID_USER
    assert len(calls) == 1


def test_a_verified_token_is_reused_instead_of_re_verified(monkeypatch):
    """Without this the app made one Auth round-trip per API request."""

    get_settings.cache_clear()
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    auth.reset_auth_cache()

    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id": VALID_USER, "email": "player@test.dev"}

    def fake_get(url, **kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr(auth._http, "get", fake_get)

    token = make_token(claims())

    for _ in range(50):
        assert str(auth.verify_access_token(token).id) == VALID_USER

    assert len(calls) == 1

    get_settings.cache_clear()
    auth.reset_auth_cache()


def test_the_cache_never_outlives_the_token(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setenv("AUTH_CACHE_SECONDS", "3600")
    get_settings.cache_clear()
    auth.reset_auth_cache()

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id": VALID_USER, "email": "player@test.dev"}

    monkeypatch.setattr(auth._http, "get", lambda url, **kwargs: Response())

    # Expires in one second, even though the cache window is an hour.
    token = make_token(claims(exp=int(time.time()) + 1))

    auth.verify_access_token(token)
    assert auth._cache.get(token) is not None

    time.sleep(1.1)
    assert auth._cache.get(token) is None

    get_settings.cache_clear()
    auth.reset_auth_cache()


def test_supabase_rejecting_the_token_surfaces_as_401(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    auth.reset_auth_cache()

    class Response:
        status_code = 401

        @staticmethod
        def json():
            return {}

    monkeypatch.setattr(auth._http, "get", lambda url, **kwargs: Response())

    with pytest.raises(HTTPException) as error:
        auth.verify_access_token(make_token(claims()))

    assert error.value.status_code == 401

    get_settings.cache_clear()
    auth.reset_auth_cache()


def test_supabase_being_unreachable_surfaces_as_503_not_401(monkeypatch):
    """An outage must not look like a bad password."""

    import requests

    get_settings.cache_clear()
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    auth.reset_auth_cache()

    def boom(url, **kwargs):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(auth._http, "get", boom)

    with pytest.raises(HTTPException) as error:
        auth.verify_access_token(make_token(claims()))

    assert error.value.status_code == 503

    get_settings.cache_clear()
    auth.reset_auth_cache()


@pytest.mark.parametrize(
    "header", [None, "", "Token abc", "Bearer", "Basic dXNlcjpwYXNz"]
)
def test_a_missing_or_wrong_authorization_scheme_is_rejected(header):
    with pytest.raises(HTTPException) as error:
        auth.get_current_user(authorization=header)

    assert error.value.status_code == 401


def test_the_bearer_scheme_is_case_insensitive(local_verification, no_network):
    token = make_token(claims())

    user = auth.get_current_user(authorization=f"bearer {token}")

    assert str(user.id) == VALID_USER
