from functools import lru_cache

from pharmacy_shared.storage import Storage

from ..config import get_settings


@lru_cache
def get_storage() -> Storage:
    return Storage.from_settings(get_settings())
