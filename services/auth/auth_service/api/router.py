"""All routers of the auth service, mounted under /api/auth/v1."""

from fastapi import APIRouter

from .admin import router as admin_router
from .auth import router as auth_router
from .pins import router as pins_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(pins_router)
