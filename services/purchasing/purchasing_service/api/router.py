"""All routers of the purchasing service, mounted under /api/purchasing/v1."""

from fastapi import APIRouter

from .orders import router as orders_router
from .payments import router as payments_router
from .suppliers import router as suppliers_router

router = APIRouter()
router.include_router(suppliers_router)
router.include_router(orders_router)
router.include_router(payments_router)
