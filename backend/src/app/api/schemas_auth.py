"""Request and response schemas for account authentication.

Passwords and invite codes use :class:`pydantic.SecretStr` so they never appear in a model repr,
traceback, or structured log by accident. Responses expose only the public account fields
(``id``, ``email``, ``role``) plus a credential-free league reference at signup and the
``has_league`` onboarding flag on ``GET /me``; password hashes and invite material are never
serialized.

User-supplied text is rejected when it contains NUL, other control characters, format characters,
or line separators. Postgres rejects NUL in text columns with a ``DataError``, so validation must
happen before a value reaches the database. The validation error handler rebuilds Pydantic's
errors without the submitted ``input`` (and without ``ctx``) so a rejected password or invite code
is never echoed back in a 4xx body.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

#: Minimum accepted password length at signup. Existing accounts can still log in with shorter
#: passwords because login only requires a non-empty value.
MIN_PASSWORD_LENGTH = 8

_MAX_PASSWORD_LENGTH = 1024


def _reject_non_printable(value: str, field: str) -> None:
    """Reject NUL, control/format characters, and line or paragraph separators in ``value``.

    ``str.isprintable`` is false for those Unicode categories, which keeps the error message free
    of the submitted value while covering more than just C0 controls.
    """
    if not value.isprintable():
        raise ValueError(f"{field} contains invalid control characters")


class _EmailRequest(BaseModel):
    """An auth request carrying an email address with shape validation."""

    email: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=320),
    ]

    @field_validator("email")
    @classmethod
    def _check_email_shape(cls, value: str) -> str:
        """Reject non-printable characters and values without one non-empty local/domain part."""
        if not value.isprintable() or any(character.isspace() for character in value):
            raise ValueError("email address contains invalid characters")
        if value.count("@") != 1:
            raise ValueError("invalid email address")
        local, domain = value.split("@")
        if not local or not domain:
            raise ValueError("invalid email address")
        return value


class SignupRequest(_EmailRequest):
    """Create an account from an invite code."""

    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=_MAX_PASSWORD_LENGTH)
    invite_code: SecretStr = Field(min_length=1, max_length=512)

    @field_validator("password")
    @classmethod
    def _check_password_characters(cls, value: SecretStr) -> SecretStr:
        _reject_non_printable(value.get_secret_value(), "password")
        return value

    @field_validator("invite_code")
    @classmethod
    def _check_invite_code_characters(cls, value: SecretStr) -> SecretStr:
        _reject_non_printable(value.get_secret_value(), "invite code")
        return value


class LoginRequest(_EmailRequest):
    """Log in with an existing account's email and password."""

    password: SecretStr = Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)

    @field_validator("password")
    @classmethod
    def _check_password_characters(cls, value: SecretStr) -> SecretStr:
        _reject_non_printable(value.get_secret_value(), "password")
        return value


class PublicUser(BaseModel):
    """The account fields safe to return to a browser."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str


class SignupLeague(BaseModel):
    """The league granted by a member invite, with no membership or credential material."""

    league_id: int
    provider: str
    external_id: str
    name: str


class SignupResponse(PublicUser):
    """A newly created account and the league its invite granted, if any."""

    league: SignupLeague | None


class MeResponse(PublicUser):
    """The signed-in account plus the flag the onboarding gate needs."""

    has_league: bool


class LogoutResponse(BaseModel):
    """Confirmation that the session cookie was cleared."""

    status: str


def error_detail(code: str, message: str) -> dict[str, str]:
    """Return the ``detail`` payload for a structured error response."""
    return {"code": code, "message": message}


async def validation_exception_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    """Return 422 errors without echoing submitted values.

    Pydantic's default body includes an ``input`` key, which would copy a rejected password or
    invite code into the response (and into browser devtools or logs). Only the location, message,
    and error type are returned.
    """
    validation_error = cast(RequestValidationError, exc)
    errors = [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", "Invalid value"),
            "type": error.get("type", "value_error"),
        }
        for error in validation_error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})
