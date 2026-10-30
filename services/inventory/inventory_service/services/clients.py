"""Other services inventory calls. Routes get them with Depends(...); tests override."""

from functools import lru_cache

from pharmacy_shared.internal import InternalClient
from pharmacy_shared.storage import Storage

from ..config import get_settings


def get_auth() -> InternalClient:
    s = get_settings()
    return InternalClient(s.auth_url, s.service_name, s.service_token)


def get_purchasing() -> InternalClient:
    s = get_settings()
    return InternalClient(s.purchasing_url, s.service_name, s.service_token)


@lru_cache
def get_storage() -> Storage:
    return Storage.from_settings(get_settings())
