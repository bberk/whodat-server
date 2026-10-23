"""Request and response schemas for account authentication.

Passwords and invite codes use :class:`pydantic.SecretStr` so they never appear in a model repr,
traceback, or structured log by accident. Responses expose only the public account fields
(``id``, ``email``, ``role``) plus a credential-free league reference at signup and the
``has_league`` onboarding flag on ``GET /me``; password hashes and invite material are never
serialized.

Every caller-supplied string (email, password, invite code) must be 7-bit ASCII; non-ASCII values
are rejected at signup so the product has one unambiguous spelling for credentials and identifiers
(no Unicode passphrases). Login is deliberately more permissive: a non-ASCII email or password is
accepted by the schema and rejected by the auth service with the same generic invalid-credentials
response as a wrong password, so the API does not reveal which validation rule failed. NUL and
other ASCII controls are still rejected before a value reaches the database, and the validation
error handler rebuilds Pydantic's errors without the submitted ``input`` (and without ``ctx``) so a
rejected password or invite code is never echoed back in a 4xx body.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

from app.security.invite_codes import INVITE_CODE_MAX_LENGTH, validate_invite_code_format
from app.validation import require_ascii

#: Minimum accepted password length at signup. Existing accounts can still log in with shorter
#: passwords because login only requires a non-empty value.
MIN_PASSWORD_LENGTH = 8

_MAX_PASSWORD_LENGTH = 1024


def _reject_ascii_controls(value: str, field: str) -> None:
    """Reject C0 controls and DEL in ``value`` even when the caller is otherwise permissive.

    The message is fixed and never repeats the submitted value. Non-ASCII control/format
    characters are handled separately: signup rejects all non-ASCII, while login lets them fall
    through to the generic invalid-credentials response.
    """
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
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
        """Reject ASCII controls and values without one non-empty local/domain part.

        A non-ASCII value is returned unchanged here for one reason: ``LoginRequest`` must not
        expose an input-validation detail for it. Signup adds its own ASCII check, and login lets
        the auth service reject the credentials with the generic 401 response.
        """
        if not value.isascii():
            return value
        _reject_ascii_controls(value, "email address")
        if any(character.isspace() for character in value):
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
    invite_code: SecretStr = Field(min_length=1, max_length=INVITE_CODE_MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def _check_email_ascii(cls, value: str) -> str:
        """Signup accepts ASCII email addresses only; the value is never echoed in an error."""
        return require_ascii(value, "email")

    @field_validator("password")
    @classmethod
    def _check_password_characters(cls, value: SecretStr) -> SecretStr:
        require_ascii(value.get_secret_value(), "password")
        _reject_ascii_controls(value.get_secret_value(), "password")
        return value

    @field_validator("invite_code")
    @classmethod
    def _check_invite_code_format(cls, value: SecretStr) -> SecretStr:
        """Require the generated URL-safe token alphabet and reject everything else."""
        validate_invite_code_format(value.get_secret_value())
        return value


# Non-ASCII login values are intentionally not a 422. They reach the auth service, which returns
# the same generic 401 as a wrong password, so a caller learns nothing about the validation rule.
class LoginRequest(_EmailRequest):
    """Log in with an existing account's email and password."""

    password: SecretStr = Field(min_length=1, max_length=_MAX_PASSWORD_LENGTH)

    @field_validator("password")
    @classmethod
    def _check_password_ascii_controls(cls, value: SecretStr) -> SecretStr:
        """Reject ASCII controls; non-ASCII is left to the generic invalid-credentials path."""
        _reject_ascii_controls(value.get_secret_value(), "password")
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
