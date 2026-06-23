from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


_BLOCKED_HOSTS = {"localhost"}
_BLOCKED_SUFFIXES = (".localhost", ".local")


def validate_public_https_url(raw_url: str, *, field: str) -> str:
    parsed = urlsplit(raw_url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{field} must be a public https URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field} must not contain credentials")
    host = parsed.hostname.lower().rstrip(".")
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        raise ValueError(f"{field} must be a public https URL")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return raw_url.rstrip("/")
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified:
        raise ValueError(f"{field} must be a public https URL")
    return raw_url.rstrip("/")
