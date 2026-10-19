"""Credential boundary for the ESPN provider.

This module is the only place that turns stored, encrypted league credentials into a configured
ESPN provider. Decryption happens here, behind the provider layer, and the plaintext cookies are
handed directly to :class:`~app.providers.espn.adapter.ESPNLeagueProvider`; they are never logged,
returned, or included in an exception message.

Services and routers pass the ciphertext tokens to :func:`create_espn_provider` and never call
:func:`app.security.crypto.decrypt` themselves.
"""

from __future__ import annotations

from app.providers.base import LeagueProvider
from app.providers.espn.adapter import ESPNLeagueProvider
from app.security.crypto import decrypt


def create_espn_provider(
    *,
    espn_s2_encrypted: str,
    espn_swid_encrypted: str,
) -> LeagueProvider:
    """Decrypt both credential tokens and return a configured ESPN provider.

    Raises :class:`app.security.crypto.CredentialCryptoError` subclasses when the key is missing or
    invalid, a token is malformed, or a token was encrypted under a different key. Callers translate
    any failure into a generic, credential-free error. Decryption is intentionally performed only
    on this provider call path.
    """
    espn_s2 = decrypt(espn_s2_encrypted)
    swid = decrypt(espn_swid_encrypted)
    return ESPNLeagueProvider(espn_s2=espn_s2, swid=swid)
