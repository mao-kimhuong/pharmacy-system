"""A stand-in for the auth service's /pin-tokens/consume (tokens are one-time)."""

from uuid import UUID, uuid4

from pharmacy_shared.errors import AppError, ErrorCode


class FakeAuth:
    def __init__(self) -> None:
        self.tokens: dict[str, dict] = {}

    def issue(self, user_id: str, action: str, kind: str = "actor", *, branches: tuple[UUID, ...] = (),
              permissions: tuple[str, ...] = ("controlled.witness",), name: str = "Staff",
              role: str = "pharmacist") -> str:  # fmt: skip
        token = uuid4().hex
        self.tokens[token] = {"action": action, "kind": kind, "person": {
            "user_id": str(user_id), "name": name, "role": role, "is_pharmacist": True,
            "branch_ids": [str(b) for b in branches], "permissions": list(permissions)}}  # fmt: skip
        return token

    async def post(self, path: str, body: dict | None = None, **_) -> dict:  # noqa: ANN003
        assert path == "/pin-tokens/consume"
        found = self.tokens.pop(body["token"], None)
        if found is None or found["action"] != body["action"] or found["kind"] != body["kind"]:
            raise AppError(ErrorCode.PIN_INVALID, "not valid", status_code=401)
        return found["person"]
