"""Unit tests for JwtAuthenticator cryptographic validation and SecurityContext creation."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from platform_core.errors import AuthenticationError
from platform_security.interfaces import Authenticator
from platform_security.jwt import JwtAuthenticator

TEST_SECRET = "super-secret-hmac-key-for-unit-testing-only-12345-at-least-32-bytes"
TEST_ISSUER = "superoffice-ai-auth"
TEST_AUDIENCE = "mcp-gateway"


@pytest.fixture
def hmac_authenticator() -> JwtAuthenticator:
    return JwtAuthenticator(
        secret_or_key=TEST_SECRET,
        algorithms=["HS256"],
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        leeway_seconds=10,
    )


@pytest.fixture
def rsa_key_pair() -> tuple[str, str]:
    """Generate an ephemeral RSA key pair for testing asymmetric signatures."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem


def create_token(
    payload: dict[str, Any],
    secret: str | bytes = TEST_SECRET,
    algorithm: str = "HS256",
) -> str:
    return jwt.encode(payload, secret, algorithm=algorithm)


def test_authenticator_implements_protocol(hmac_authenticator: JwtAuthenticator) -> None:
    assert isinstance(hmac_authenticator, Authenticator)


@pytest.mark.asyncio
async def test_valid_hs256_token_authentication(hmac_authenticator: JwtAuthenticator) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": "user_42",
        "role": "L2",
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "exp": (now + timedelta(hours=8)).timestamp(),  # Valid multi-hour token
        "nbf": (now - timedelta(seconds=5)).timestamp(),
        "iat": now.timestamp(),
        "production_write": True,
        "attachment_access": False,
        "scopes": ["diagnostic_read", "ticket_read"],
    }
    raw_token = create_token(payload)
    context = await hmac_authenticator.authenticate(f"Bearer {raw_token}")

    assert context.is_authenticated is True
    assert context.principal.user_id == "user_42"
    assert context.principal.role == "L2"
    assert "production_write" in context.principal.scopes
    assert context.attributes["production_write"] is True
    assert context.attributes["attachment_access"] is False


@pytest.mark.asyncio
async def test_max_token_age_enforcement_rejects_old_token() -> None:
    authenticator = JwtAuthenticator(
        secret_or_key=TEST_SECRET,
        algorithms=["HS256"],
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        leeway_seconds=5,
        max_token_age_seconds=300,  # Max 5 minutes age
    )
    now = datetime.now(UTC)
    payload = {
        "sub": "user_old_issued",
        "role": "L1",
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "exp": (now + timedelta(hours=2)).timestamp(),
        "iat": (now - timedelta(minutes=15)).timestamp(),  # Issued 15 min ago
    }
    raw_token = create_token(payload)
    with pytest.raises(AuthenticationError, match="maximum allowed lifespan"):
        await authenticator.authenticate(raw_token)


@pytest.mark.asyncio
async def test_valid_asymmetric_rsa_token_authentication(rsa_key_pair: tuple[str, str]) -> None:
    private_pem, public_pem = rsa_key_pair
    authenticator = JwtAuthenticator(
        secret_or_key=public_pem,
        algorithms=["RS256"],
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
    )
    now = datetime.now(UTC)
    payload = {
        "sub": "admin_expert",
        "role": "L3",
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "exp": (now + timedelta(hours=1)).timestamp(),
        "iat": now.timestamp(),
        "attachment_access": True,
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")
    context = await authenticator.authenticate(token)

    assert context.principal.user_id == "admin_expert"
    assert context.principal.role == "L3"
    assert "attachment_access" in context.principal.scopes
    assert context.attributes["attachment_access"] is True


@pytest.mark.asyncio
async def test_expired_token_rejected(hmac_authenticator: JwtAuthenticator) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": "user_expired",
        "role": "L1",
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "exp": (now - timedelta(minutes=5)).timestamp(),
        "iat": (now - timedelta(hours=1)).timestamp(),
    }
    raw_token = create_token(payload)
    with pytest.raises(AuthenticationError) as exc_info:
        await hmac_authenticator.authenticate(f"Bearer {raw_token}")
    assert "expired" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_invalid_signature_rejected(hmac_authenticator: JwtAuthenticator) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": "user_hacker",
        "role": "L3",
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "exp": (now + timedelta(hours=1)).timestamp(),
        "iat": now.timestamp(),
    }
    forged_token = create_token(payload, secret="attacker-forged-secret-key-999-at-least-32-bytes")
    with pytest.raises(AuthenticationError) as exc_info:
        await hmac_authenticator.authenticate(forged_token)
    assert "signature" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_issuer_mismatch_rejected(hmac_authenticator: JwtAuthenticator) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": "user_bad_iss",
        "role": "L1",
        "iss": "untrusted-external-idp",
        "aud": TEST_AUDIENCE,
        "exp": (now + timedelta(hours=1)).timestamp(),
        "iat": now.timestamp(),
    }
    raw_token = create_token(payload)
    with pytest.raises(AuthenticationError) as exc_info:
        await hmac_authenticator.authenticate(raw_token)
    assert "issuer mismatch" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_audience_mismatch_rejected(hmac_authenticator: JwtAuthenticator) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": "user_bad_aud",
        "role": "L1",
        "iss": TEST_ISSUER,
        "aud": "wrong-audience-target",
        "exp": (now + timedelta(hours=1)).timestamp(),
        "iat": now.timestamp(),
    }
    raw_token = create_token(payload)
    with pytest.raises(AuthenticationError) as exc_info:
        await hmac_authenticator.authenticate(raw_token)
    assert "audience mismatch" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_missing_sub_rejected(hmac_authenticator: JwtAuthenticator) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": "",
        "role": "L1",
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "exp": (now + timedelta(hours=1)).timestamp(),
        "iat": now.timestamp(),
    }
    raw_token = create_token(payload)
    with pytest.raises(AuthenticationError) as exc_info:
        await hmac_authenticator.authenticate(raw_token)
    assert "sub" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_invalid_role_claim_rejected(hmac_authenticator: JwtAuthenticator) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": "root_user",
        "role": "SUPERUSER_ADMIN",
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "exp": (now + timedelta(hours=1)).timestamp(),
        "iat": now.timestamp(),
    }
    raw_token = create_token(payload)
    with pytest.raises(AuthenticationError) as exc_info:
        await hmac_authenticator.authenticate(raw_token)
    assert "invalid role" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_empty_or_malformed_token_rejected(hmac_authenticator: JwtAuthenticator) -> None:
    with pytest.raises(AuthenticationError):
        await hmac_authenticator.authenticate("")
    with pytest.raises(AuthenticationError):
        await hmac_authenticator.authenticate("Bearer ")
    with pytest.raises(AuthenticationError):
        await hmac_authenticator.authenticate("NotEvenBase64.AtAll")
