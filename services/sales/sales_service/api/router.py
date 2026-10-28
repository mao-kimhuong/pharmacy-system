"""All routers of the sales service, mounted under /api/sales/v1."""

from fastapi import APIRouter

from .sales import router as sales_router

router = APIRouter()
router.include_router(sales_router)
