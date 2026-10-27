from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.visibility import drop_fields

from ..services.common import COST_FIELDS, can_see_cost


def respond(model: BaseModel, user: CurrentUser, status_code: int = 200) -> JSONResponse:
    """The response, minus purchase prices for users who may not see them."""
    data: Any = model.model_dump(mode="json")
    if not can_see_cost(user):
        data = drop_fields(data, COST_FIELDS)
    return JSONResponse(data, status_code=status_code)
