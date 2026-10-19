"""Request and response schemas for account authentication.

Passwords and invite codes use :class:`pydantic.SecretStr` so they never appear in a model repr,
traceback, or structured log by accident. Responses expose only the public account fields
(``id``, ``email``, ``role``); password hashes and invite material are never serialized.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

#: Minimum accepted password length at signup. Existing accounts can still log in with shorter
#: passwords because login only requires a non-empty value.
MIN_PASSWORD_LENGTH = 8

_MAX_PASSWORD_LENGTH = 1024


class _EmailRequest(BaseModel):
    """An auth request carrying an email address with basic shape validation."""

    email: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=320),
    ]

    @field_validator("email")
    @classmethod
    def _check_email_shape(cls, value: str) -> str:
        """Reject values without exactly one non-empty local and domain part."""
        if value.count("@") != 1:
            raise ValueError("invalid email address")
        local, domain = value.split("@")
        if not local or not domain or any(character.isspace() for character in value):
            raise ValueError("invalid email address")
        return value


class SignupRequest(_EmailRequest):
    """Create an account from an invite code."""

    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=_MAX_PASSWORD_LENGTH)
    invite_code: SecretStr = Field(min_length=1, max_length=512)


class LoginRequest(_EmailRequest):
    """Log in with an existing account's email and password."""

    password: SecretStr = Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)


class PublicUser(BaseModel):
    """The account fields safe to return to a browser."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str


class LogoutResponse(BaseModel):
    """Confirmation that the session cookie was cleared."""

    status: str


class ErrorDetail(BaseModel):
    """Machine-readable error code plus a human-readable message."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Error body shape used by the auth routes."""

    detail: ErrorDetail


def error_detail(code: str, message: str) -> dict[str, str]:
    """Return the ``detail`` payload for a structured error response."""
    return {"code": code, "message": message}
