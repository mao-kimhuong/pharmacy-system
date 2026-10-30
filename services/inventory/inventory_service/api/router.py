"""All routers of the inventory service, mounted under /api/inventory/v1."""

from fastapi import APIRouter

from .inventory import router as inventory_router
from .reorder import router as reorder_router
from .s5 import router as s5_router
from .transfers import router as transfers_router

router = APIRouter()
router.include_router(inventory_router)
router.include_router(s5_router)
router.include_router(transfers_router)
router.include_router(reorder_router)
