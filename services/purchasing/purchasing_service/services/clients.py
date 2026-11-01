"""Services purchasing calls; routes get them with Depends, tests override."""

from pharmacy_shared.internal import InternalClient

from ..config import get_settings


def get_inventory() -> InternalClient:
    s = get_settings()
    return InternalClient(s.inventory_url, s.service_name, s.service_token)


def get_auth() -> InternalClient:
    """PIN and witness tokens (controlled lines of a supplier return)."""
    s = get_settings()
    return InternalClient(s.auth_url, s.service_name, s.service_token)
