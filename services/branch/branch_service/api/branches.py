from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, current_user, requires

from ..db import db
from ..features import FEATURES
from ..models import Branch, BranchSettings
from ..schemas.branch import (
    BranchCreate,
    BranchOut,
    BranchSettingsOut,
    BranchSettingsUpdate,
    BranchUpdate,
    FeatureOut,
    FeatureUpdate,
    ReasonRequest,
)
from ..services import branches as svc

router = APIRouter()
manage_branches = requires("settings.branches")


@router.get("/branches", response_model=list[BranchOut], tags=["branches"])
async def list_branches(
    include_inactive: bool = False,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
) -> list[Branch]:
    """Your branches (the owner: all). Inactive ones only with `settings.branches`."""
    return await svc.list_branches(session, user, include_inactive)


@router.post("/branches", response_model=BranchOut, status_code=201, tags=["branches"])
async def create_branch(
    body: BranchCreate,
    user: CurrentUser = Depends(manage_branches),
    session: AsyncSession = Depends(db.session),
) -> Branch:
    return await svc.create_branch(session, user, body.model_dump())


@router.get("/branches/{branch_id}", response_model=BranchOut, tags=["branches"])
async def get_branch(
    branch_id: UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(db.session)
) -> Branch:
    return await svc.get_branch(session, user, branch_id)


@router.patch("/branches/{branch_id}", response_model=BranchOut, tags=["branches"])
async def update_branch(
    branch_id: UUID,
    body: BranchUpdate,
    user: CurrentUser = Depends(manage_branches),
    session: AsyncSession = Depends(db.session),
) -> Branch:
    return await svc.update_branch(session, user, branch_id, body.model_dump(exclude_unset=True))


@router.post("/branches/{branch_id}/deactivate", response_model=BranchOut, tags=["branches"])
async def deactivate_branch(
    branch_id: UUID,
    body: ReasonRequest,
    user: CurrentUser = Depends(manage_branches),
    session: AsyncSession = Depends(db.session),
) -> Branch:
    """Staff can no longer be assigned to it; its history stays."""
    return await svc.set_active(session, user, branch_id, False, body.reason)


@router.post("/branches/{branch_id}/activate", response_model=BranchOut, tags=["branches"])
async def activate_branch(
    branch_id: UUID, user: CurrentUser = Depends(manage_branches), session: AsyncSession = Depends(db.session)
) -> Branch:
    return await svc.set_active(session, user, branch_id, True, None)


@router.get("/branches/{branch_id}/settings", response_model=BranchSettingsOut, tags=["branches"])
async def get_settings(
    branch_id: UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(db.session)
) -> BranchSettings:
    return (await svc.get_branch(session, user, branch_id)).settings


@router.put("/branches/{branch_id}/settings", response_model=BranchSettingsOut, tags=["branches"])
async def update_settings(
    branch_id: UUID,
    body: BranchSettingsUpdate,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
) -> BranchSettings:
    """Expiry alert days, receipt header/footer, branch price override."""
    data = body.model_dump(exclude_unset=True)
    if body.khqr is not None:
        data["khqr"] = body.khqr.model_dump()  # with its defaults (currencies)
    return await svc.update_settings(session, user, branch_id, data)


@router.get("/features", response_model=list[FeatureOut], tags=["features"])
async def list_features(
    _: CurrentUser = Depends(current_user), session: AsyncSession = Depends(db.session)
) -> list[FeatureOut]:
    """Which optional features are on. The front end hides the `hides` menu items when off."""
    state = await svc.list_features(session)
    return [FeatureOut(key=f.key, label=f.label, enabled=state[f.key], hides=list(f.hides)) for f in FEATURES]


@router.put("/features/{key}", response_model=list[FeatureOut], tags=["features"])
async def set_feature(
    key: str,
    body: FeatureUpdate,
    user: CurrentUser = Depends(requires("settings.features")),
    session: AsyncSession = Depends(db.session),
) -> list[FeatureOut]:
    state = await svc.set_feature(session, user, key, body.enabled)
    return [FeatureOut(key=f.key, label=f.label, enabled=state[f.key], hides=list(f.hides)) for f in FEATURES]
