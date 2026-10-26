"""All routers of the document service are included here.

Mounted under /api/documents/v1. Endpoints for this service are listed in
docs/spec.md (Screen -> API map, Menu structure, Endpoint reference).
"""

from fastapi import APIRouter

router = APIRouter()

# Example for sprint work:
# from .<feature> import router as <feature>_router
# router.include_router(<feature>_router, prefix="/<feature>", tags=["<feature>"])
