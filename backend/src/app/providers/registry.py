"""Explicit registry for provider instances."""

from app.providers.base import LeagueProvider


class ProviderRegistry:
    """Register and retrieve provider instances by their unique provider ID."""

    def __init__(self) -> None:
        self._providers: dict[str, LeagueProvider] = {}

    def register(self, provider: LeagueProvider) -> None:
        """Add a provider; duplicate IDs are rejected without replacing entries."""
        if provider.provider_id in self._providers:
            raise ValueError(f"Provider already registered: {provider.provider_id}")
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> LeagueProvider:
        """Return the provider for an ID, raising KeyError when it is unknown."""
        return self._providers[provider_id]
