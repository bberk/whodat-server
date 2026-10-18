"""ESPN provider adapter.

This is the ONLY package that may import `espn_api` or contain ESPN-specific logic
(ARCHITECTURE.md section 3, AC-PR-03).

Public API:
    ESPNLeagueProvider - LeagueProvider implementation for ESPN leagues
"""

from app.providers.espn.adapter import ESPNLeagueProvider

__all__ = ["ESPNLeagueProvider"]
