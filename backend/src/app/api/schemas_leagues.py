"""Request and response schemas for league membership, owners, and refresh.

Credential fields use :class:`pydantic.SecretStr`, so they are masked in model representations and
are never serialized back. Validation messages never repeat the submitted value (the shared
validation handler drops Pydantic's ``input``/``ctx``), and responses expose only whether a
membership has credentials, never a token or a hash.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.security.invite_codes import (
    DEFAULT_INVITE_LIFETIME_DAYS,
    INVITE_CODE_MAX_LENGTH,
    MAX_INVITE_LIFETIME_DAYS,
    validate_invite_code_format,
)
from app.validation import MAX_EXTERNAL_ID_LENGTH, normalize_external_id, require_ascii

#: Bounds keep obviously wrong seasons and ids out before the service touches the database.
MIN_SEASON = 2000
MAX_SEASON = 2100

_MAX_CREDENTIAL_LENGTH = 4096


def _require_printable(value: str, field_name: str) -> None:
    """Reject control characters and line separators without echoing the value."""
    if not value.isprintable():
        raise ValueError(f"{field_name} contains invalid control characters")


class AddLeagueRequest(BaseModel):
    """Add a league with admin credentials (or a public league without them)."""

    model_config = ConfigDict(extra="forbid", validate_default=True)

    espn_league_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=MAX_EXTERNAL_ID_LENGTH,
        ),
    ]
    season: Annotated[int | None, Field(ge=MIN_SEASON, le=MAX_SEASON)] = None
    espn_s2: SecretStr | None = Field(default=None, min_length=1, max_length=_MAX_CREDENTIAL_LENGTH)
    espn_swid: SecretStr | None = Field(
        default=None, min_length=1, max_length=_MAX_CREDENTIAL_LENGTH
    )

    @field_validator("espn_league_id")
    @classmethod
    def _check_league_id(cls, value: str) -> str:
        """Trim, NFC-normalize, and accept only id characters (no whitespace or markup)."""
        return normalize_external_id(value)

    @field_validator("espn_s2", "espn_swid")
    @classmethod
    def _check_credential(cls, value: SecretStr | None) -> SecretStr | None:
        """Reject non-ASCII, empty, or non-printable cookies before they reach the service."""
        if value is not None:
            secret = value.get_secret_value()
            require_ascii(secret, "credential")
            _require_printable(secret, "credential")
        return value

    @model_validator(mode="after")
    def _check_credential_pair(self) -> AddLeagueRequest:
        """Require both cookies or neither; one half is not usable."""
        if (self.espn_s2 is None) != (self.espn_swid is None):
            raise ValueError("espn_s2 and espn_swid must be supplied together")
        return self


class RedeemInviteRequest(BaseModel):
    """Redeem a member invite to join its league."""

    model_config = ConfigDict(extra="forbid")

    invite_code: SecretStr = Field(min_length=1, max_length=INVITE_CODE_MAX_LENGTH)

    @field_validator("invite_code")
    @classmethod
    def _check_invite_code(cls, value: SecretStr) -> SecretStr:
        """Require the generated URL-safe token alphabet and reject everything else."""
        validate_invite_code_format(value.get_secret_value())
        return value


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


class RedeemInviteResponse(BaseModel):
    """The membership created by redeeming a member invite."""

    league: LeagueSummary


class SeasonsResponse(BaseModel):
    """Stored seasons for one league."""

    seasons: list[int]


class AddSeasonRequest(BaseModel):
    """Add and sync one more season for an existing league."""

    model_config = ConfigDict(extra="forbid")

    season: Annotated[int, Field(ge=MIN_SEASON, le=MAX_SEASON)]


class AddSeasonResponse(BaseModel):
    """The season added to a league and the weeks the sync ingested."""

    league_id: int
    season: int
    weeks_synced: list[int]


class SeasonSettingsSummary(BaseModel):
    """One stored season's admin settings: cup week, week range, and last provider sync."""

    season: int
    cup_week: int | None
    regular_season_length: int
    last_refreshed_at: datetime | None


class SeasonSettingsResponse(BaseModel):
    """Every stored season for a league, ascending, for the admin seasons table."""

    seasons: list[SeasonSettingsSummary]


class SeasonRefreshResponse(BaseModel):
    """The season refreshed through the provider and the weeks its sync ingested."""

    season: int
    weeks_synced: list[int]


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


class CupWeekResponse(BaseModel):
    """A season's cup week and the week range an admin may choose from."""

    season: int
    cup_week: int | None
    regular_season_length: int


class CupWeekUpdateRequest(BaseModel):
    """Set a season's cup week, or clear it with ``null``.

    The field is required so a malformed body cannot silently clear an existing cup week; the upper
    bound depends on stored season metadata and is validated by the service.
    """

    model_config = ConfigDict(extra="forbid")

    cup_week: Annotated[int | None, Field(ge=1)]


class LeagueMemberSummary(BaseModel):
    """One account that belongs to a league, with no password or credential material.

    ``email`` is the account identifier because the application has no username field.
    ``has_credentials`` only says whether the membership holds stored league cookies; their values
    are never exposed.
    """

    user_id: int
    email: str
    role: str
    owner_id: int | None
    owner_name: str | None
    has_credentials: bool


class LeagueMembersResponse(BaseModel):
    """Every account associated with a league, ordered by email."""

    members: list[LeagueMemberSummary]


class CreateInviteRequest(BaseModel):
    """Generate one member invite for this league or one league-less admin invite."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["admin", "member"]
    expires_in_days: Annotated[int, Field(ge=1, le=MAX_INVITE_LIFETIME_DAYS)] = (
        DEFAULT_INVITE_LIFETIME_DAYS
    )


class CreateInviteResponse(BaseModel):
    """The one and only place a newly created invite's raw code is returned.

    Only the hash is stored. The client must show this code once and cannot retrieve it later.
    """

    code: str
    role: str
    league_id: int | None
    expires_at: datetime
