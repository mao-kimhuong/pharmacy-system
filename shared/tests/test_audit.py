from uuid import UUID

from pharmacy_shared.audit import audit_payload, changes
from pharmacy_shared.auth import CurrentUser


def test_changes_keeps_only_changed_fields() -> None:
    before, after = changes(
        {"name": "A", "phone": "01", "role": "cashier"}, {"name": "B", "phone": "01", "role": "cashier"}
    )
    assert before == {"name": "A"}
    assert after == {"name": "B"}


def test_changes_includes_added_and_removed_fields() -> None:
    before, after = changes({"a": 1}, {"b": 2})
    assert before == {"a": 1, "b": None}
    assert after == {"a": None, "b": 2}


def test_audit_payload_names_the_actor() -> None:
    actor = CurrentUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        role="owner",
        branch_ids=frozenset(),
        is_pharmacist=False,
    )
    payload = audit_payload(
        service="branch", action="branch.created", entity_type="branch", entity_id="b1", actor=actor
    )
    assert payload["actor_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["actor_role"] == "owner"
    assert payload["before"] == {} and payload["after"] == {}
