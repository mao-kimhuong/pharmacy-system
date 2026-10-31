"""All routers of the catalog service, mounted under /api/catalog/v1."""

from fastapi import APIRouter

from .imports import router as imports_router
from .lookups import router as lookups_router
from .medicines import router as medicines_router
from .s7 import router as s7_router

router = APIRouter()
router.include_router(lookups_router)
router.include_router(medicines_router)
router.include_router(imports_router)
router.include_router(s7_router)
