from __future__ import annotations

import re
from typing import Any


DNS1123_LABEL_PATTERN = r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$"
DNS1123_SUBDOMAIN_PATTERN = (
    r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?)*$"
)
KUBERNETES_DATA_KEY_PATTERN = r"^[A-Za-z0-9._-]+$"


def is_dns1123_label(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 63
        and re.fullmatch(DNS1123_LABEL_PATTERN, value) is not None
    )


def is_dns1123_subdomain(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 253
        and re.fullmatch(DNS1123_SUBDOMAIN_PATTERN, value) is not None
    )


def is_kubernetes_data_key(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 253
        and re.fullmatch(KUBERNETES_DATA_KEY_PATTERN, value) is not None
    )


def validate_secret_reference(reference: Any) -> tuple[str, str, str]:
    if not isinstance(reference, dict) or set(reference) != {"namespace", "name", "key"}:
        raise ValueError("secret_ref must contain exactly namespace, name, and key")
    namespace, name, key = (reference[field] for field in ("namespace", "name", "key"))
    if not is_dns1123_label(namespace):
        raise ValueError("secret_ref namespace must be a DNS-1123 label")
    if not is_dns1123_subdomain(name):
        raise ValueError("secret_ref name must be a DNS-1123 subdomain")
    if not is_kubernetes_data_key(key):
        raise ValueError("secret_ref key must be a Kubernetes data key")
    return namespace, name, key
