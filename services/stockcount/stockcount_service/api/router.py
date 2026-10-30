"""All routers of the stockcount service, mounted under /api/stockcount/v1."""

from fastapi import APIRouter

from .counts import router as counts_router

router = APIRouter()
router.include_router(counts_router)
