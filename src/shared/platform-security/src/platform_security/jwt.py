"""Cryptographic JWT token authentication and SecurityContext construction."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import jwt

from platform_core.errors import AuthenticationError
from platform_core.models import PrincipalIdentity
from platform_security.interfaces import Authenticator
from platform_security.models import SecurityContext

ALLOWED_ROLES = {"L1", "L2", "L3"}


class JwtAuthenticator(Authenticator):
    """Deterministic cryptographic JWT authenticator validating inbound tokens."""

    def __init__(
        self,
        secret_or_key: str | bytes,
        *,
        algorithms: list[str] | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        leeway_seconds: int = 60,
        max_token_age_seconds: int | None = None,
    ) -> None:
        self.secret_or_key = secret_or_key
        self.algorithms = algorithms or ["HS256", "RS256", "ES256"]
        self.issuer = issuer
        self.audience = audience
        self.leeway_seconds = leeway_seconds
        self.max_token_age_seconds = max_token_age_seconds

    def _decode_claims(self, raw_token: str) -> dict[str, Any]:
        """Decode and validate raw JWT token signature and standard claims."""
        decode_options: dict[str, Any] = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iat": True,
            "require": ["exp", "sub"],
        }
        if self.issuer is not None:
            decode_options["verify_iss"] = True
        if self.audience is not None:
            decode_options["verify_aud"] = True

        try:
            claims = dict(
                jwt.decode(
                    raw_token,
                    self.secret_or_key,
                    algorithms=self.algorithms,
                    issuer=self.issuer,
                    audience=self.audience,
                    leeway=self.leeway_seconds,
                    options=decode_options,  # type: ignore[arg-type]
                )
            )
        except jwt.ExpiredSignatureError as e:
            raise AuthenticationError("Token has expired.") from e
        except jwt.InvalidIssuerError as e:
            raise AuthenticationError("Token issuer mismatch.") from e
        except jwt.InvalidAudienceError as e:
            raise AuthenticationError("Token audience mismatch.") from e
        except (jwt.ImmatureSignatureError, jwt.InvalidIssuedAtError) as e:
            raise AuthenticationError("Token timestamp is invalid or in the future.") from e
        except jwt.PyJWTError as e:
            raise AuthenticationError(
                "Invalid authentication token or cryptographic signature."
            ) from e
        except Exception as e:
            raise AuthenticationError(f"Unexpected token decoding error: {e}") from e

        # Optional maximum token age enforcement
        if self.max_token_age_seconds is not None:
            iat = claims.get("iat")
            if iat is not None:
                now_ts = datetime.now(UTC).timestamp()
                age = now_ts - float(iat)
                if age > (self.max_token_age_seconds + self.leeway_seconds):
                    raise AuthenticationError(
                        f"Token age ({age:.0f}s) exceeds maximum allowed lifespan "
                        f"of {self.max_token_age_seconds}s.",
                        details={"max_token_age_seconds": self.max_token_age_seconds},
                    )

        return claims

    async def authenticate(self, credentials_or_token: str) -> SecurityContext:
        """Extract and validate JWT Bearer token, producing a trusted SecurityContext."""
        if not credentials_or_token or not credentials_or_token.strip():
            raise AuthenticationError("Missing authentication token.")

        raw_token = credentials_or_token.strip()
        if raw_token.lower().startswith("bearer "):
            raw_token = raw_token[7:].strip()

        if not raw_token:
            raise AuthenticationError("Malformed Authorization header: empty Bearer token.")

        claims = self._decode_claims(raw_token)

        sub = str(claims.get("sub", "")).strip()
        if not sub:
            raise AuthenticationError("Token missing non-empty 'sub' subject claim.")

        role = str(claims.get("role", "L1")).upper().strip()
        if role not in ALLOWED_ROLES:
            raise AuthenticationError(
                f"Invalid role claim '{role}'. Must be one of: {sorted(ALLOWED_ROLES)}",
                details={"role": role},
            )

        raw_scopes = claims.get("scopes", [])
        scopes_list = list(raw_scopes) if isinstance(raw_scopes, (list, tuple)) else []
        production_write = bool(claims.get("production_write", False))
        attachment_access = bool(claims.get("attachment_access", False))

        if production_write and "production_write" not in scopes_list:
            scopes_list.append("production_write")
        if attachment_access and "attachment_access" not in scopes_list:
            scopes_list.append("attachment_access")

        jti = str(claims.get("jti", f"tok_{uuid4().hex[:12]}"))

        principal = PrincipalIdentity(
            user_id=sub,
            role=role,
            scopes=tuple(scopes_list),
        )

        return SecurityContext(
            principal=principal,
            token_id=jti,
            is_authenticated=True,
            attributes={
                "production_write": production_write,
                "attachment_access": attachment_access,
                "issuer": claims.get("iss"),
                "audience": claims.get("aud"),
                "claims": {k: v for k, v in claims.items() if k not in ("sub", "role")},
            },
        )
