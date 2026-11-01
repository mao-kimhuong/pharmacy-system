"""All routers of the sales service, mounted under /api/sales/v1."""

from fastapi import APIRouter

from .extras import router as extras_router
from .khqr import router as khqr_router
from .sales import router as sales_router

router = APIRouter()
router.include_router(sales_router)
router.include_router(extras_router)
router.include_router(khqr_router)
