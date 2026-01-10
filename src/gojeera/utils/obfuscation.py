from __future__ import annotations

from gojeera.config import CONFIGURATION


def obfuscate_if_enabled(value: str | None) -> str:
    """Obfuscate a value if obfuscate_personal_info is enabled.

    Args:
        value: The value to potentially obfuscate.

    Returns:
        Either the original value or 'obfuscated' if obfuscation is enabled.
    """
    if not value:
        return value or ''

    if CONFIGURATION.get().obfuscate_personal_info:
        return 'obfuscated'
    return value


def obfuscate_url(url: str | None) -> str:
    """Obfuscate a URL if obfuscate_personal_info is enabled.

    Args:
        url: The URL to potentially obfuscate.

    Returns:
        Either the original URL or 'obfuscated' if obfuscation is enabled.
    """
    return obfuscate_if_enabled(url)


def obfuscate_account_id(account_id: str | None) -> str:
    """Obfuscate an account ID if obfuscate_personal_info is enabled.

    Args:
        account_id: The account ID to potentially obfuscate.

    Returns:
        Either the original account ID or 'obfuscated' if obfuscation is enabled.
    """
    return obfuscate_if_enabled(account_id)
