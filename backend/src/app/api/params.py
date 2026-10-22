"""Reusable path-parameter constraints for the HTTP layer.

Malformed ids and seasons are rejected while FastAPI parses the request, before any dependency can
touch the service or the database. That keeps a negative id, a zero id, a non-numeric path segment,
or an unsupported year from becoming a service call or a SQL predicate.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Path

from app.api.schemas_leagues import MAX_SEASON, MIN_SEASON

#: A stored entity id, which is always a positive integer.
PositiveIdPath = Annotated[int, Path(ge=1)]

#: A season must be a whole year in the range the application supports.
SeasonPath = Annotated[int, Path(ge=MIN_SEASON, le=MAX_SEASON)]

LeagueIdPath = PositiveIdPath
UserIdPath = PositiveIdPath
MemberUserIdPath = PositiveIdPath
