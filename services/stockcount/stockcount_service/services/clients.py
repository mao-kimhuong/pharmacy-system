"""Services stockcount calls; routes get them with Depends, tests override."""

from dataclasses import dataclass

from pharmacy_shared.internal import InternalClient

from ..config import get_settings


@dataclass(frozen=True)
class Clients:
    auth: InternalClient
    inventory: InternalClient


def get_clients() -> Clients:
    s = get_settings()
    return Clients(
        auth=InternalClient(s.auth_url, s.service_name, s.service_token),
        inventory=InternalClient(s.inventory_url, s.service_name, s.service_token),
    )
