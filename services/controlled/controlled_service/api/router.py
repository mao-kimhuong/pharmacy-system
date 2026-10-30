"""All routers of the controlled service, mounted under /api/controlled/v1."""

from fastapi import APIRouter

from .register import router as register_router

router = APIRouter()
router.include_router(register_router)
