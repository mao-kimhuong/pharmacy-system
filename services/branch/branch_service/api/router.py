"""All routers of the branch service, mounted under /api/branch/v1."""

from fastapi import APIRouter

from .branches import router as branches_router

router = APIRouter()
router.include_router(branches_router)
