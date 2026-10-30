"""The services the sale saga calls. A route gets them with
`clients: Clients = Depends(get_clients)`; tests override get_clients."""

from dataclasses import dataclass

from pharmacy_shared.internal import InternalClient

from ..config import get_settings


@dataclass(frozen=True)
class Clients:
    inventory: InternalClient
    customers: InternalClient
    prescription: InternalClient
    auth: InternalClient


def get_clients() -> Clients:
    s = get_settings()
    return Clients(
        inventory=InternalClient(s.inventory_url, s.service_name, s.service_token),
        customers=InternalClient(s.customers_url, s.service_name, s.service_token),
        prescription=InternalClient(s.prescription_url, s.service_name, s.service_token),
        auth=InternalClient(s.auth_url, s.service_name, s.service_token),
    )
