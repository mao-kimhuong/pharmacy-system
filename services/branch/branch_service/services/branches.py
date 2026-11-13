"""Branches, branch settings and feature switches. Rules:

- Branches are never deleted: deactivate (with a reason) / activate.
- The code (2-10 capital letters or digits) is unique and fixed after creation.
- Staff see only their own branches; the owner sees all.
- Creating/editing branches needs `settings.branches`; a branch's settings need
  `settings.branch_settings` and access to that branch (or `settings.branches`).
- Every change: a branch.* event (other services keep a copy) + a User Log entry.
"""

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import changes, record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..features import FEATURES, KEYS
from ..models import Branch, BranchSettings, FeatureSwitch, OutboxEvent

SERVICE = "branch"
_CODE = re.compile(r"^[A-Z0-9]{2,10}$")


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Branch not found", status_code=404)


def _event_payload(branch: Branch) -> dict[str, Any]:
    return {
        "branch_id": str(branch.id),
        "code": branch.code,
        "name_km": branch.name_km,
        "name_en": branch.name_en,
        "is_active": branch.is_active,
    }


def _audit(
    session: AsyncSession, actor: CurrentUser, action: str, branch: Branch, before: dict, after: dict
) -> None:
    record_audit(
        session,
        OutboxEvent,
        service=SERVICE,
        action=action,
        entity_type="branch",
        entity_id=branch.id,
        actor=actor,
        branch_id=branch.id,
        before=before,
        after=after,
    )


async def list_branches(session: AsyncSession, actor: CurrentUser, include_inactive: bool) -> list[Branch]:
    query = select(Branch).order_by(Branch.code)
    if not actor.is_owner:
        query = query.where(Branch.id.in_(actor.branch_ids or [UUID(int=0)]))
    if not (include_inactive and actor.has("settings.branches")):
        query = query.where(Branch.is_active.is_(True))
    return list((await session.execute(query)).scalars())


async def get_branch(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID, *, lock: bool = False
) -> Branch:
    if not actor.can_access_branch(branch_id):
        raise _not_found()  # same answer as missing: do not reveal other branches
    query = select(Branch).where(Branch.id == branch_id)
    if lock:
        query = query.with_for_update()
    branch = (await session.execute(query)).scalar_one_or_none()
    if branch is None:
        raise _not_found()
    return branch


async def create_branch(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> Branch:
    code = str(data["code"]).strip().upper()
    if not _CODE.match(code):
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "Code: 2-10 capital letters or digits, e.g. PP1", status_code=422
        )
    if (await session.execute(select(Branch.id).where(Branch.code == code))).first():
        raise AppError(ErrorCode.DUPLICATE_CODE, "A branch with this code already exists", status_code=409)
    branch = Branch(
        code=code,
        name_km=data["name_km"].strip(),
        name_en=data["name_en"].strip(),
        address=(data.get("address") or "").strip(),
        phone=(data.get("phone") or "").strip(),
        license_no=(data.get("license_no") or "").strip(),
        created_by=actor.id,
        settings=BranchSettings(),
    )
    session.add(branch)
    await session.flush()
    add_event(session, OutboxEvent, "branch.created", _event_payload(branch))
    _audit(session, actor, "branch.created", branch, {}, branch.safe_fields())
    await session.commit()
    return branch


async def update_branch(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID, data: dict[str, Any]
) -> Branch:
    branch = await get_branch(session, actor, branch_id, lock=True)
    before = branch.safe_fields()
    for field in ("name_km", "name_en", "address", "phone", "license_no"):
        if field in data and data[field] is not None:
            setattr(branch, field, str(data[field]).strip())
    after = branch.safe_fields()
    if after != before:
        add_event(session, OutboxEvent, "branch.updated", _event_payload(branch))
        _audit(session, actor, "branch.updated", branch, *changes(before, after))
    await session.commit()
    return branch


async def set_active(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID, active: bool, reason: str | None
) -> Branch:
    branch = await get_branch(session, actor, branch_id, lock=True)
    if branch.is_active == active:
        return branch
    branch.is_active = active
    action = "branch.activated" if active else "branch.deactivated"
    add_event(session, OutboxEvent, action, _event_payload(branch))
    _audit(session, actor, action, branch, {"is_active": not active}, {"is_active": active, "reason": reason})
    await session.commit()
    return branch


def _check_settings_access(actor: CurrentUser, branch_id: UUID) -> None:
    if actor.has("settings.branches"):
        return
    actor.require("settings.branch_settings")
    actor.require_branch(branch_id)


def _clean_alert_days(days: list[int]) -> list[int]:
    cleaned = sorted({int(d) for d in days}, reverse=True)
    if not 1 <= len(cleaned) <= 5 or any(d < 1 or d > 730 for d in cleaned):
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "Give 1 to 5 alert days, each between 1 and 730", status_code=422
        )
    return cleaned


def _clean_hours(hours: dict[str, list[str]] | None) -> dict[str, list[str]] | None:
    """Open before close, same day (no shifts past midnight)."""
    if not hours:
        return None
    for day, (opens, closes) in hours.items():
        if opens >= closes:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"{day}: opening time must be before closing time",
                           status_code=422, details={"field": "opening_hours", "reason": "open_after_close"})  # fmt: skip
    return {day: list(v) for day, v in hours.items()}


async def update_settings(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID, data: dict[str, Any]
) -> BranchSettings:
    _check_settings_access(actor, branch_id)
    branch = await get_branch(session, actor, branch_id, lock=True)
    settings = branch.settings
    before = settings.safe_fields()
    if "expiry_alert_days" in data:
        settings.expiry_alert_days = _clean_alert_days(data["expiry_alert_days"])
    for field in (
        "receipt_header",
        "receipt_footer",
        "price_override_enabled",
        "allow_opened_pack_returns",
        "rx_valid_days",
        "dispensing_label_size",
        "controlled_rx_valid_days",
        "double_count_above_usd",
        "owner_approval_above_usd",
        "shrinkage_approval_usd",
        "reorder_sales_days",
        "reorder_safety_days",
        "reorder_lead_days",
        "near_expiry_transfer_days",
        "order_deposit_on_cancel",
        "max_discount_pct",
        "receipt_lang",
        "khqr",
        "refill_reminder_days",
    ):
        if field in data:
            setattr(settings, field, data[field])
    if "opening_hours" in data:
        settings.opening_hours = _clean_hours(data["opening_hours"])
    after = settings.safe_fields()
    if after != before:
        add_event(session, OutboxEvent, "branch.settings_updated", {"branch_id": str(branch.id), **after})
        _audit(session, actor, "branch.settings_updated", branch, *changes(before, after))
    await session.commit()
    return settings


# ---------------------------------------------------------------- feature switches


async def sync_features(session: AsyncSession) -> None:
    """Start-up: add new feature keys with their default; never change existing ones."""
    for f in FEATURES:
        await session.execute(
            insert(FeatureSwitch).values(key=f.key, enabled=f.default).on_conflict_do_nothing()
        )
    await session.commit()


async def list_features(session: AsyncSession) -> dict[str, bool]:
    rows = (await session.execute(select(FeatureSwitch))).scalars()
    stored = {r.key: r.enabled for r in rows}
    return {f.key: stored.get(f.key, f.default) for f in FEATURES}


async def set_feature(session: AsyncSession, actor: CurrentUser, key: str, enabled: bool) -> dict[str, bool]:
    if key not in KEYS:
        raise AppError(ErrorCode.UNKNOWN_FEATURE, f"Unknown feature: {key}", status_code=404)
    row = (
        await session.execute(select(FeatureSwitch).where(FeatureSwitch.key == key).with_for_update())
    ).scalar_one_or_none()
    if row is None:
        row = FeatureSwitch(key=key, enabled=KEYS[key].default)
        session.add(row)
    if row.enabled != enabled:
        record_audit(
            session,
            OutboxEvent,
            service=SERVICE,
            action="feature.changed",
            entity_type="feature",
            entity_id=key,
            actor=actor,
            before={"enabled": row.enabled},
            after={"enabled": enabled},
        )
        row.enabled = enabled
        row.updated_by = actor.id
        add_event(session, OutboxEvent, "feature.changed", {"key": key, "enabled": enabled})
    await session.commit()
    return await list_features(session)
