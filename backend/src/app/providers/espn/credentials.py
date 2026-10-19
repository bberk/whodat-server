"""Credential boundary for the ESPN provider.

This module is the only place that turns stored, encrypted league credentials into a configured
ESPN provider. Decryption happens here, behind the provider layer, and the plaintext cookies are
handed directly to :class:`~app.providers.espn.adapter.ESPNLeagueProvider`; they are never logged,
returned, or included in an exception message.

Services and routers pass ciphertext tokens to :func:`create_espn_provider` and never call
:func:`app.security.crypto.decrypt` themselves. When no tokens are supplied (a public league added
by an admin without credentials) the provider is configured with explicit empty cookies rather
than falling back to the environment ``ESPN_S2``/``ESPN_SWID`` values.
"""

from __future__ import annotations

from app.providers.base import LeagueProvider
from app.providers.espn.adapter import ESPNLeagueProvider
from app.security.crypto import decrypt


def create_espn_provider(
    *,
    espn_s2_encrypted: str | None = None,
    espn_swid_encrypted: str | None = None,
) -> LeagueProvider:
    """Return an ESPN provider configured from optional encrypted credential tokens.

    With both tokens, decrypt them and pass the plaintext only to the provider. With neither, pass
    explicit empty cookies so the adapter never reads the environment credential path during API
    request handling. Supplying exactly one token is a programming error and raises ``ValueError``
    before any decryption.

    Raises :class:`app.security.crypto.CredentialCryptoError` subclasses when the key is missing or
    invalid, a token is malformed, or a token was encrypted under a different key. Callers translate
    any failure into a generic, credential-free error. Decryption is intentionally performed only
    on this provider call path.
    """
    if espn_s2_encrypted is None and espn_swid_encrypted is None:
        return ESPNLeagueProvider(espn_s2="", swid="")
    if espn_s2_encrypted is None or espn_swid_encrypted is None:
        raise ValueError("both encrypted credential tokens must be supplied together")

    espn_s2 = decrypt(espn_s2_encrypted)
    swid = decrypt(espn_swid_encrypted)
    return ESPNLeagueProvider(espn_s2=espn_s2, swid=swid)
