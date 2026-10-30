"""/internal/v1 – the document service reads the register for the PDF."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.register import RegisterOut, RegisterQuery
from ..services import register

router = APIRouter()


@router.post("/register", response_model=RegisterOut)
async def read_register(
    body: RegisterQuery, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    return await register.entries(session, body.branch_id, body.medicine_id, body.date_from, body.date_to)
