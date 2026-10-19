"""Request and response schemas for league membership, owners, and refresh.

Credential fields use :class:`pydantic.SecretStr`, so they are masked in model representations and
are never serialized back. Validation messages never repeat the submitted value (the shared
validation handler drops Pydantic's ``input``/``ctx``), and responses expose only whether a
membership has credentials, never a token or a hash.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

#: Bounds keep obviously wrong seasons and ids out before the service touches the database.
MIN_SEASON = 2000
MAX_SEASON = 2100

_MAX_CREDENTIAL_LENGTH = 4096


def _require_printable(value: str, field_name: str) -> None:
    """Reject control characters and line separators without echoing the value."""
    if not value.isprintable():
        raise ValueError(f"{field_name} contains invalid control characters")


class AddLeagueRequest(BaseModel):
    """Add a league with admin credentials or join an existing league without them."""

    model_config = ConfigDict(extra="forbid", validate_default=True)

    espn_league_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    season: Annotated[int | None, Field(ge=MIN_SEASON, le=MAX_SEASON)] = None
    espn_s2: SecretStr | None = Field(default=None, min_length=1, max_length=_MAX_CREDENTIAL_LENGTH)
    espn_swid: SecretStr | None = Field(
        default=None, min_length=1, max_length=_MAX_CREDENTIAL_LENGTH
    )

    @field_validator("espn_league_id")
    @classmethod
    def _check_league_id(cls, value: str) -> str:
        """Reject non-printable or whitespace-containing league ids."""
        _require_printable(value, "espn_league_id")
        if any(character.isspace() for character in value):
            raise ValueError("espn_league_id contains invalid characters")
        return value

    @field_validator("espn_s2", "espn_swid")
    @classmethod
    def _check_credential(cls, value: SecretStr | None) -> SecretStr | None:
        """Reject empty or non-printable cookies before they reach the service."""
        if value is not None:
            _require_printable(value.get_secret_value(), "credential")
        return value

    @model_validator(mode="after")
    def _check_credential_pair(self) -> AddLeagueRequest:
        """Require both cookies or neither; one half is not usable."""
        if (self.espn_s2 is None) != (self.espn_swid is None):
            raise ValueError("espn_s2 and espn_swid must be supplied together")
        return self


class LeagueSummary(BaseModel):
    """A membership's league, with no credential material."""

    league_id: int
    provider: str
    external_id: str
    name: str
    owner_id: int | None
    has_credentials: bool


class AddLeagueResponse(BaseModel):
    """Result of adding or joining a league."""

    league: LeagueSummary
    season: int
    weeks_synced: list[int]


class SeasonsResponse(BaseModel):
    """Stored seasons for one league."""

    seasons: list[int]


class OwnerSummary(BaseModel):
    """A league owner the caller may associate with their membership."""

    id: int
    external_id: str
    display_name: str


class OwnersResponse(BaseModel):
    """Owners available for the caller's owner association."""

    owners: list[OwnerSummary]


class OwnerUpdateRequest(BaseModel):
    """Set or clear the caller's own owner association."""

    model_config = ConfigDict(extra="forbid")

    owner_id: Annotated[int | None, Field(ge=1)] = None


class OwnerUpdateResponse(BaseModel):
    """The caller's membership after the owner association changed."""

    league: LeagueSummary


class RefreshResponse(BaseModel):
    """Summary of one league-wide refresh."""

    league_id: int
    season: int
    weeks_synced: list[int]
    weeks_with_vp_recomputed: list[int]
