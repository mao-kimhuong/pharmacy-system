"""All routers of the prescription service, mounted under /api/prescription/v1."""

from fastapi import APIRouter

from .patients import router as patients_router
from .prescriptions import router as prescriptions_router

router = APIRouter()
router.include_router(patients_router)
router.include_router(prescriptions_router)
