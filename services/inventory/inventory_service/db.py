from pharmacy_shared.db import Database

from .config import get_settings

db = Database(get_settings().database_url)
