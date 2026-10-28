"""This service's own declarative base (its own MetaData)."""

from pharmacy_shared.db import make_base

Base = make_base()
