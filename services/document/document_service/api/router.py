"""All routers of the document service, mounted under /api/documents/v1."""

from fastapi import APIRouter

from .render import router as render_router

router = APIRouter()
router.include_router(render_router)
